"""Untrusted external hosts are mocked at the transport, not the download behavior."""

import asyncio
import gzip

import httpx
import pytest

from app.schemas.fulltext import FullTextCandidate
from app.schemas.research import FullTextLocation


def response(status, *, content=b"", headers=None):
    return httpx.Response(status, headers=headers, stream=httpx.ByteStream(content))


def candidate(url="https://arxiv.org/pdf/one"):
    return FullTextCandidate(
        provider="openalex",
        external_id="W123",
        source_label="OpenAlex",
        url=url,
        location=FullTextLocation(pdf_url=url, is_oa=True),
    )


class Resolver:
    def __init__(self, addresses=("8.8.8.8",)):
        self.addresses = addresses
        self.calls = []

    async def resolve(self, host, port):
        self.calls.append((host, port))
        return self.addresses


async def fetch(response, *, url="https://arxiv.org/pdf/one", addresses=("8.8.8.8",)):
    from app.integrations.pdf_download import PDFDownloader

    requests = []

    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response

    resolver = Resolver(addresses)
    downloader = PDFDownloader(
        ["arxiv.org", "aclanthology.org"],
        resolver=resolver,
        transport_factory=lambda: httpx.MockTransport(respond),
    )
    try:
        result = await downloader.fetch(candidate(url))
        return result, requests, resolver
    finally:
        await downloader.aclose()


async def test_valid_pdf_bytes_are_returned_with_pinned_identity():
    result, requests, resolver = await fetch(
        response(200, content=b"%PDF-1.7\nfixture", headers={"Content-Type": "application/pdf"})
    )
    assert result.outcome == "downloaded" and result.data == b"%PDF-1.7\nfixture"
    assert requests[0].url.host == "8.8.8.8"
    assert requests[0].headers["Host"] == "arxiv.org"
    assert requests[0].extensions["sni_hostname"] == "arxiv.org"
    assert not any(
        key in requests[0].headers for key in ("Authorization", "Cookie", "x-api-key", "Referer")
    )
    assert resolver.calls == [("arxiv.org", 443)]


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (401, "access_required"),
        (403, "blocked"),
        (404, "not_found"),
        (410, "not_found"),
        (429, "rate_limited"),
        (500, "unavailable"),
    ],
)
async def test_http_outcomes_describe_observed_barrier(status, outcome):
    result, _, _ = await fetch(response(status, headers={"Retry-After": "999"}))
    assert result.outcome == outcome and result.data is None
    assert result.response_status == status
    if status == 429:
        assert result.retry_after == 300


@pytest.mark.parametrize(
    ("url", "outcome"),
    [
        ("http://127.0.0.1/private", "unsafe_url"),
        ("https://arxiv.org@127.0.0.1/private", "unsafe_url"),
        ("https://user:password@arxiv.org/private", "unsafe_url"),
        ("file:///etc/passwd", "unsafe_url"),
        ("https://arxiv.org:8443/private", "unsafe_url"),
        ("https://arxiv.org:bad/private", "unsafe_url"),
        ("https://arxiv.org.evil.test/private", "unsupported_source"),
        ("https://arxiv.org/" + "x" * 4096, "unsafe_url"),
    ],
)
async def test_unsafe_destination_never_connects(url, outcome):
    result, requests, _ = await fetch(response(200, content=b"%PDF-1.7"), url=url)
    assert result.outcome == outcome
    assert requests == []


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.1",),
        ("169.254.169.254",),
        ("100.64.0.1",),
        ("::1",),
        ("::ffff:8.8.8.8",),
        ("8.8.8.8", "192.168.0.1"),
        ("224.0.0.1",),
    ],
)
async def test_nonpublic_or_mixed_dns_answers_never_connect(addresses):
    result, requests, _ = await fetch(response(200, content=b"%PDF-1.7"), addresses=addresses)
    assert result.outcome == "unsafe_url"
    assert requests == []


async def test_relative_redirect_keeps_original_host_and_validates_new_host():
    def respond(request):
        if request.url.path == "/pdf/one":
            return response(302, headers={"Location": "/pdf/two"})
        if request.url.path == "/pdf/two":
            return response(302, headers={"Location": "https://aclanthology.org/final.pdf"})
        return response(200, content=b"%PDF-1.7\nfinal")

    result, requests, resolver = await fetch(respond)
    assert result.outcome == "downloaded"
    assert result.final_url == "https://aclanthology.org/final.pdf"
    assert [request.headers["Host"] for request in requests] == [
        "arxiv.org",
        "arxiv.org",
        "aclanthology.org",
    ]
    assert len(resolver.calls) == 3


@pytest.mark.parametrize("location", ["http://arxiv.org/pdf/down", "http://127.0.0.1/private"])
async def test_redirect_downgrade_or_private_target_is_rejected(location):
    result, requests, _ = await fetch(response(302, headers={"Location": location}))
    assert result.outcome == "unsafe_url" and len(requests) == 1


async def test_redirect_loop_has_at_most_five_hops():
    result, requests, _ = await fetch(response(302, headers={"Location": "/pdf/one"}))
    assert result.outcome == "unavailable"
    assert len(requests) == 6


async def test_login_redirect_reports_authentication_without_following():
    result, requests, _ = await fetch(
        response(302, headers={"Location": "https://login.example.edu/Shibboleth.sso/Login"})
    )
    assert result.outcome == "access_required" and len(requests) == 1


@pytest.mark.parametrize(
    "headers", [{"Content-Type": "text/html"}, {"Content-Type": "application/pdf"}, {}]
)
async def test_html_is_not_a_pdf_or_a_proven_paywall(headers):
    result, _, _ = await fetch(
        response(200, content=b"<html>Please sign in or purchase</html>", headers=headers)
    )
    assert result.outcome == "invalid_pdf" and result.data is None
    assert "paywall" not in result.reason.lower()


async def test_claimed_size_limit_rejects_without_reading_body():
    result, _, _ = await fetch(
        response(200, content=b"%PDF-1.7", headers={"Content-Length": "26214401"})
    )
    assert result.outcome == "invalid_pdf" and result.data is None


async def test_chunked_size_limit_rejects_overflow():
    result, _, _ = await fetch(response(200, content=b"%PDF-1.7\n" + b"x" * (25 * 1024 * 1024)))
    assert result.outcome == "invalid_pdf" and result.data is None


async def test_compressed_bomb_is_rejected_before_decompression():
    result, _, _ = await fetch(
        response(
            200,
            content=gzip.compress(b"%PDF-1.7\n" + b"x" * (25 * 1024 * 1024)),
            headers={"Content-Encoding": "gzip"},
        )
    )
    assert result.outcome == "invalid_pdf" and result.data is None


async def test_slow_dns_is_inside_candidate_deadline(monkeypatch):
    from app.integrations import pdf_download

    monkeypatch.setattr(pdf_download, "CANDIDATE_SECONDS", 0.01)

    class SlowResolver:
        called = False

        async def resolve(self, _host, _port):
            self.called = True
            await asyncio.sleep(10)

    resolver = SlowResolver()
    downloader = pdf_download.PDFDownloader(["arxiv.org"], resolver=resolver)
    try:
        result = await asyncio.wait_for(downloader.fetch(candidate()), 1)
        assert result.outcome == "unavailable"
        assert resolver.called
    finally:
        await downloader.aclose()


async def test_dns_rebinding_on_redirect_is_rejected_before_second_connection():
    from app.integrations.pdf_download import PDFDownloader

    class ChangingResolver:
        count = 0

        async def resolve(self, _host, _port):
            self.count += 1
            return ("8.8.8.8",) if self.count == 1 else ("10.0.0.1",)

    requests = []

    def redirect(request):
        requests.append(request)
        return response(302, headers={"Location": "/pdf/two", "Set-Cookie": "secret=value"})

    downloader = PDFDownloader(
        ["arxiv.org"],
        resolver=ChangingResolver(),
        transport_factory=lambda: httpx.MockTransport(redirect),
    )
    try:
        result = await downloader.fetch(candidate())
        assert result.outcome == "unsafe_url" and len(requests) == 1
        assert "Cookie" not in requests[0].headers
    finally:
        await downloader.aclose()


@pytest.mark.parametrize("cancel", [False, True])
async def test_stalled_or_cancelled_response_closes_stream(monkeypatch, cancel):
    from app.integrations import pdf_download

    started = asyncio.Event()

    class Stalled(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            started.set()
            yield b"%PDF-1.7\n"
            await asyncio.sleep(10)

        async def aclose(self):
            self.closed = True

    stream = Stalled()
    monkeypatch.setattr(pdf_download, "CANDIDATE_SECONDS", 1 if cancel else 0.02)
    downloader = pdf_download.PDFDownloader(
        ["arxiv.org"],
        resolver=Resolver(),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    )
    try:
        task = asyncio.create_task(downloader.fetch(candidate()))
        await asyncio.wait_for(started.wait(), 1)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(task, 1)
            assert result.outcome == "unavailable"
        assert stream.closed
    finally:
        await downloader.aclose()
