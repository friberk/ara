"""Real TLS checks for the original hostname after connecting to a validated literal IP."""

import asyncio
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from httpcore._backends.anyio import AnyIOBackend

from app.integrations.openalex_content import ContentDownloader

STORAGE = "a452eddbbe06eb7d02f4879cee70d29c.r2.cloudflarestorage.com"


class LoopbackTLSTransport(httpx.AsyncHTTPTransport):
    # Capture the real transport before the external-network guard is installed.
    # This test's LocalBackend always connects to its loopback server, even though
    # the downloader's request retains a synthetic public IP and TLS identity.
    handle_async_request = httpx.AsyncHTTPTransport.handle_async_request


async def test_real_tls_validates_each_hops_original_hostname(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    await asyncio.to_thread(
        subprocess.run,
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=content.openalex.org",
            "-addext",
            "subjectAltName=DNS:content.openalex.org",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path.startswith("/works/W1.pdf"):
                self.send_response(302)
                self.send_header("Location", f"https://{STORAGE}/openalex-pdfs/W1.pdf?X-Amz=1")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            content = b"%PDF-1.7\nTLS fixture"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    names = []
    context.set_servername_callback(lambda _socket, name, _context: names.append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Resolver:
        async def resolve(self, _host, _port):
            return ("8.8.8.8",)

    class LocalBackend(AnyIOBackend):
        async def connect_tcp(
            self,
            host,
            port,
            timeout=None,  # noqa: ASYNC109 -- upstream httpcore backend signature
            local_address=None,
            socket_options=None,
        ):
            assert host == "8.8.8.8" and port == 443
            return await super().connect_tcp("127.0.0.1", server.server_port, timeout=timeout)

    def factory():
        transport = LoopbackTLSTransport(
            verify=ssl.create_default_context(cafile=str(cert)),
            limits=httpx.Limits(max_keepalive_connections=0),
        )
        transport._pool._network_backend = LocalBackend()
        return transport

    downloader = ContentDownloader(resolver=Resolver(), transport_factory=factory)
    try:
        assert (await downloader.fetch("W2", "fixture-key")).outcome == "downloaded"
        # OpenAlex's certificate does not cover its storage host, so that hop must fail TLS.
        assert (await downloader.fetch("W1", "fixture-key")).outcome == "unavailable"
        assert names == ["content.openalex.org", "content.openalex.org", STORAGE]
    finally:
        await downloader.aclose()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
