"""Connect to validated public IPs while retaining the original HTTP/TLS identity."""

import asyncio
import ipaddress
import socket
from collections.abc import Callable, Sequence
from typing import Protocol
from urllib.parse import urlsplit

import httpx


class Resolver(Protocol):
    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]: ...


class DNSResolver:
    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        rows = await asyncio.get_running_loop().getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        return tuple(dict.fromkeys(row[4][0] for row in rows))


class DownloadPolicyError(ValueError):
    def __init__(self, outcome: str, reason: str):
        super().__init__(reason)
        self.outcome, self.reason = outcome, reason


class ManagedStream(httpx.AsyncByteStream):
    def __init__(self, stream, transport, owner):
        self.stream, self.transport, self.owner = stream, transport, owner

    async def __aiter__(self):
        async for block in self.stream:
            yield block

    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            await self.transport.aclose()
            self.owner.discard(self.transport)


class PublicPDFTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        allowed_hosts: Sequence[str],
        *,
        resolver: Resolver | None = None,
        transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
    ):
        self.allowed_hosts = set(allowed_hosts)
        self.resolver = resolver or DNSResolver()
        self.factory = transport_factory or (
            lambda: httpx.AsyncHTTPTransport(
                retries=0, limits=httpx.Limits(max_keepalive_connections=0, max_connections=1)
            )
        )
        self.transports = set()

    def validate(self, url: str) -> tuple[str, int]:
        try:
            if len(url) > 4096 or any(ord(char) <= 32 for char in url):
                raise ValueError
            parts = urlsplit(url)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
            ):
                raise ValueError
            hostname = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
            port = parts.port or (443 if parts.scheme == "https" else 80)
            if port != (443 if parts.scheme == "https" else 80):
                raise ValueError
            try:
                ipaddress.ip_address(hostname)
            except ValueError:
                pass
            else:
                raise ValueError
        except (ValueError, UnicodeError):
            raise DownloadPolicyError(
                "unsafe_url", "The PDF link has an unsafe destination."
            ) from None
        if hostname not in self.allowed_hosts:
            raise DownloadPolicyError(
                "unsupported_source",
                "Automatic download is not configured for this host. "
                "Open it in your browser or upload the PDF.",
            )
        return hostname, port

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname, port = self.validate(str(request.url))
        addresses = await self.resolver.resolve(hostname, port)
        try:
            ips = [ipaddress.ip_address(address) for address in addresses]
            if not ips or any(
                not ip.is_global
                or ip.is_multicast
                or (ip.version == 6 and ip.ipv4_mapped is not None)
                for ip in ips
            ):
                raise ValueError
        except ValueError:
            raise DownloadPolicyError(
                "unsafe_url", "The PDF host resolves to a non-public destination."
            ) from None
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in {"accept", "accept-encoding", "user-agent"}
        }
        headers["Host"] = hostname
        pinned = httpx.Request(
            "GET",
            request.url.copy_with(host=str(ips[0])),
            headers=headers,
            extensions={**request.extensions, "sni_hostname": hostname},
        )
        transport = self.factory()
        self.transports.add(transport)
        try:
            response = await transport.handle_async_request(pinned)
        except BaseException:
            await transport.aclose()
            self.transports.discard(transport)
            raise
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=ManagedStream(response.stream, transport, self.transports),
            extensions=response.extensions,
        )

    async def aclose(self):
        for transport in list(self.transports):
            await transport.aclose()
        self.transports.clear()
