"""OpenAlex's content endpoint is mocked at the transport, not the download behavior (ARA-087)."""

import asyncio
import gzip
import logging

import httpx
import pytest

KEY = "fixture-openalex-key"
STORAGE = "https://a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com"
SIGNED = f"{STORAGE}/openalex-pdfs/W123.pdf?X-Amz-Signature=fixture-signature"
PDF = b"%PDF-1.7\nfixture"


def response(status, *, content=b"", headers=None):
    return httpx.Response(status, headers=headers, stream=httpx.ByteStream(content))


class Resolver:
    def __init__(self, addresses=("8.8.8.8",)):
        self.addresses = addresses
        self.calls = []

    async def resolve(self, host, port):
        self.calls.append((host, port))
        return self.addresses


def stored(request):
    """The content endpoint's documented shape: a redirect to a signed storage link."""
    if request.headers["Host"] == "content.openalex.org":
        return response(302, headers={"Location": SIGNED})
    return response(200, content=PDF, headers={"Content-Type": "application/pdf"})


async def fetch(answer=stored, *, work_id="W123", addresses=("8.8.8.8",), resolver=None):
    from app.integrations.openalex_content import ContentDownloader

    requests = []

    def respond(request):
        requests.append(request)
        return answer(request) if callable(answer) else answer

    resolver = resolver or Resolver(addresses)
    downloader = ContentDownloader(
        resolver=resolver, transport_factory=lambda: httpx.MockTransport(respond)
    )
    try:
        return await downloader.fetch(work_id, KEY), requests, resolver
    finally:
        await downloader.aclose()


async def test_a_stored_pdf_downloads_through_the_signed_storage_link():
    result, requests, resolver = await fetch()
    assert result.outcome == "downloaded" and result.data == PDF
    first, second = requests
    assert first.headers["Host"] == "content.openalex.org"
    assert first.url.path == "/works/W123.pdf" and first.url.params["api_key"] == KEY
    assert first.extensions["sni_hostname"] == "content.openalex.org"
    # The key goes only to OpenAlex; the signed link already authorizes storage.
    assert second.headers["Host"] == "a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com"
    assert KEY not in str(second.url) and "Authorization" not in second.headers
    assert second.url.params["X-Amz-Signature"] == "fixture-signature"
    assert [call[0] for call in resolver.calls] == [
        "content.openalex.org",
        "a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com",
    ]


async def test_neither_the_key_nor_the_signed_link_is_logged_or_returned(caplog):
    with caplog.at_level(logging.DEBUG):
        result, _, _ = await fetch()
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert KEY not in logged and "fixture-signature" not in logged
    assert KEY not in repr(result) and "fixture-signature" not in repr(result)


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (404, "not_stored"),
        (401, "api_key_required"),
        (403, "api_key_required"),
        (500, "unavailable"),
    ],
)
async def test_content_endpoint_statuses_name_the_outcome(status, outcome):
    result, requests, _ = await fetch(response(status, content=b'{"error":"fixture"}'))
    assert result.outcome == outcome and result.data is None
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("headers", "wait"),
    [
        ({"Retry-After": "120", "X-RateLimit-Reset": "5000"}, 120),
        ({"X-RateLimit-Reset": "5000", "X-RateLimit-Remaining": "0"}, 5000),
        ({"Retry-After": "999999"}, 86400),
        ({}, None),
    ],
)
async def test_a_refusal_reports_openalexs_own_wait(headers, wait):
    result, _, _ = await fetch(response(429, headers=headers))
    assert result.outcome == "rate_limited" and result.retry_after == wait


@pytest.mark.parametrize(
    "location",
    [
        "https://arxiv.org/pdf/W123",
        "http://a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com/openalex-pdfs/W123.pdf",
        "https://evil.r2.cloudflarestorage.com/openalex-pdfs/W123.pdf",
        "https://127.0.0.1/private",
    ],
)
async def test_redirects_leave_openalex_only_for_its_storage(location):
    result, requests, _ = await fetch(response(302, headers={"Location": location}))
    assert result.outcome == "unsafe_url" and len(requests) == 1


async def test_a_merged_work_redirect_keeps_the_key_on_openalex():
    def merged(request):
        if request.url.path == "/works/W123.pdf":
            return response(301, headers={"Location": "/works/W456.pdf"})
        return stored(request)

    result, requests, _ = await fetch(merged)
    assert result.outcome == "downloaded"
    assert requests[1].url.path == "/works/W456.pdf" and requests[1].url.params["api_key"] == KEY


async def test_redirect_loops_stop():
    result, requests, _ = await fetch(response(302, headers={"Location": "/works/W123.pdf"}))
    assert result.outcome == "unavailable" and len(requests) <= 4


@pytest.mark.parametrize("work_id", ["W123/../../admin", "123", "W12x", ""])
async def test_only_openalex_work_ids_are_requested(work_id):
    result, requests, _ = await fetch(work_id=work_id)
    assert result.outcome == "not_stored" and requests == []


@pytest.mark.parametrize(
    "addresses", [("127.0.0.1",), ("10.0.0.1",), ("169.254.169.254",), ("8.8.8.8", "192.168.0.1")]
)
async def test_nonpublic_dns_answers_never_connect(addresses):
    result, requests, _ = await fetch(addresses=addresses)
    assert result.outcome == "unsafe_url" and requests == []


async def test_storage_dns_rebinding_is_rejected_before_connecting():
    class Changing(Resolver):
        async def resolve(self, host, port):
            self.calls.append((host, port))
            return ("8.8.8.8",) if len(self.calls) == 1 else ("10.0.0.1",)

    result, requests, _ = await fetch(resolver=Changing())
    assert result.outcome == "unsafe_url" and len(requests) == 1


@pytest.mark.parametrize(
    "answer",
    [
        response(200, content=b"<html>Not a PDF</html>", headers={"Content-Type": "text/html"}),
        response(
            200, content=b"<html>Not a PDF</html>", headers={"Content-Type": "application/pdf"}
        ),
        response(200, content=PDF, headers={"Content-Length": "26214401"}),
        response(200, content=b"%PDF-1.7\n" + b"x" * (25 * 1024 * 1024)),
        response(
            200,
            content=gzip.compress(b"%PDF-1.7\n" + b"x" * 1024),
            headers={"Content-Encoding": "gzip"},
        ),
    ],
)
async def test_bodies_must_be_bounded_unencoded_pdfs(answer):
    def storage(request):
        return stored(request) if request.headers["Host"] == "content.openalex.org" else answer

    result, _, _ = await fetch(storage)
    assert result.outcome == "invalid_pdf" and result.data is None


@pytest.mark.parametrize("cancel", [False, True])
async def test_a_stalled_download_times_out_and_closes(monkeypatch, cancel):
    from app.integrations import openalex_content

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
    monkeypatch.setattr(openalex_content, "DOWNLOAD_SECONDS", 1 if cancel else 0.02)
    downloader = openalex_content.ContentDownloader(
        resolver=Resolver(),
        transport_factory=lambda: httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
    )
    try:
        task = asyncio.create_task(downloader.fetch("W123", KEY))
        await asyncio.wait_for(started.wait(), 1)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await asyncio.wait_for(task, 1)).outcome == "unavailable"
        assert stream.closed
    finally:
        await downloader.aclose()


async def lookup(answer, **identity):
    from app.core.config import Settings
    from app.integrations.openalex_content import stored_work

    requests = []

    def respond(request):
        requests.append(request)
        return answer(request) if callable(answer) else answer

    settings = Settings(_env_file=None, openalex_api_key=KEY)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        return await stored_work(http, settings, **identity), requests


async def test_a_saved_openalex_work_is_checked_with_a_free_lookup():
    work, requests = await lookup(
        httpx.Response(200, json={"id": "https://openalex.org/W123", "has_content": {"pdf": True}}),
        work_id="W123",
    )
    assert (work.work_id, work.has_pdf) == ("W123", True)
    (request,) = requests
    assert request.url.host == "api.openalex.org" and request.url.path == "/works/W123"
    assert request.url.params["select"] == "id,has_content"


async def test_a_doi_resolves_the_openalex_work():
    work, requests = await lookup(
        httpx.Response(
            200, json={"id": "https://openalex.org/W456", "has_content": {"pdf": False}}
        ),
        doi="10.1000/Exact-Case",
    )
    assert (work.work_id, work.has_pdf) == ("W456", False)
    assert requests[0].url.path == "/works/doi:10.1000/Exact-Case"


async def test_no_matching_work_or_identity_means_no_stored_copy():
    work, _ = await lookup(httpx.Response(404, json={"error": "Not found"}), doi="10.1000/none")
    assert work is None
    work, requests = await lookup(httpx.Response(500))
    assert work is None and requests == []


@pytest.mark.parametrize(
    "body",
    [
        {"id": 5, "has_content": {"pdf": True}},
        {"id": "https://openalex.org/W1", "has_content": "yes"},
    ],
)
async def test_malformed_lookups_fail_safely(body):
    from app.core.errors import AppError

    with pytest.raises(AppError) as error:
        await lookup(httpx.Response(200, json=body), work_id="W1")
    assert error.value.code == "PROVIDER_INVALID_RESPONSE"


async def test_a_rate_limited_lookup_reports_its_wait():
    from app.core.errors import AppError

    with pytest.raises(AppError) as error:
        await lookup(httpx.Response(429, headers={"Retry-After": "40"}), work_id="W1")
    assert error.value.code == "PROVIDER_RATE_LIMITED" and error.value.retry_after == 40


async def test_resources_own_and_close_the_content_downloader():
    from app.core.config import Settings
    from app.core.resources import Resources
    from app.integrations.openalex_content import ContentDownloader

    resources = Resources(Settings(_env_file=None))
    try:
        assert isinstance(resources.pdf_downloader, ContentDownloader)
    finally:
        await resources.close()
    assert resources.pdf_downloader.transport.transports == set()
