"""What the real API does when the client goes away during an upload (ARA-119).

The app runs under real uvicorn on a loopback port and the client is a raw TCP socket, so the
disconnect is a real one. Only the order of events is fixed: a gate holds the route, before it
writes anything, until the socket has closed.
"""

import asyncio
import contextlib
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from support.front_matter import toolchain_pdf
from support.live_api import live_api

from app.models.research import Document, DocumentUploadRequest, Paper

pytestmark = pytest.mark.integration

BOUNDARY = "ara-upload-boundary"


def multipart(data: bytes, request_id: str) -> bytes:
    parts = [
        f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="request_id"\r\n\r\n'
        f"{request_id}\r\n",
        f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="p.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n",
    ]
    return "".join(parts).encode() + data + f"\r\n--{BOUNDARY}--\r\n".encode()


def head(length: int) -> bytes:
    return (
        "POST /api/v1/documents HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
        f"Content-Type: multipart/form-data; boundary={BOUNDARY}\r\n"
        f"Content-Length: {length}\r\n\r\n"
    ).encode()


@pytest.fixture
async def server(resources):
    async with live_api(resources) as port:
        yield port


async def counts(resources) -> tuple[int, int, int]:
    async with resources.sessions() as session:
        return (
            await session.scalar(select(func.count(Paper.id))),
            await session.scalar(select(func.count(Document.id))),
            await session.scalar(select(func.count(DocumentUploadRequest.request_id))),
        )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="ARA-119: the upload continues after the client has gone and adds the paper.",
)
async def test_a_client_gone_after_sending_the_whole_body_adds_no_paper(
    resources, server, monkeypatch
):
    """Given a Cancel after the whole file has arrived, the library gains no paper."""
    from app.routes import documents

    reached, release = asyncio.Event(), asyncio.Event()
    finished = asyncio.Event()
    real = documents.upload

    # The form is parsed and the route has started, but nothing has been written yet.
    async def gated(*args, **kwargs):
        reached.set()
        await release.wait()
        try:
            return await real(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(documents, "upload", gated)
    body = multipart(toolchain_pdf(), str(uuid4()))
    _, writer = await asyncio.open_connection("127.0.0.1", server)
    writer.write(head(len(body)) + body)
    await writer.drain()
    try:
        await asyncio.wait_for(reached.wait(), 10)
        assert await counts(resources) == (0, 0, 0)
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.2)  # Let the server see the disconnect before the handler goes on.
    finally:
        release.set()
    # A handler that honors the disconnect never finishes the upload, so this wait just expires.
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(finished.wait(), 3)
    papers, documents_added, _ = await counts(resources)
    assert (papers, documents_added) == (0, 0), (
        f"{papers} paper(s) and {documents_added} document(s) were added after the client left"
    )


async def test_a_client_gone_part_way_through_the_body_stores_nothing(resources, server):
    """Given a Cancel while the file is still being sent, nothing is stored."""
    body = multipart(toolchain_pdf(), str(uuid4()))
    reader, writer = await asyncio.open_connection("127.0.0.1", server)
    writer.write(head(len(body)) + body[: len(body) // 2])
    await writer.drain()
    await asyncio.sleep(0.2)
    writer.close()
    await writer.wait_closed()
    await asyncio.sleep(1)
    assert await counts(resources) == (0, 0, 0)
    objects = await resources.storage_call(
        lambda: list(
            resources.storage.list_objects(resources.settings.minio_bucket, recursive=True)
        )
    )
    assert objects == []


async def test_a_client_that_stays_gets_its_paper(resources, server):
    """The control: over the same socket path, a completed upload is accepted and stored."""
    body = multipart(toolchain_pdf(), str(uuid4()))
    reader, writer = await asyncio.open_connection("127.0.0.1", server)
    writer.write(head(len(body)) + body)
    await writer.drain()
    answer = await asyncio.wait_for(reader.read(), 15)
    writer.close()
    await writer.wait_closed()
    assert answer.startswith(b"HTTP/1.1 202"), answer[:200]
    assert await counts(resources) == (1, 1, 1)
