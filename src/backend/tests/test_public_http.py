"""Real TLS checks for the original hostname after connecting to a validated literal IP."""

import asyncio
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from httpcore._backends.anyio import AnyIOBackend

from app.integrations.pdf_download import PDFDownloader
from app.schemas.fulltext import FullTextCandidate
from app.schemas.research import FullTextLocation


async def test_real_tls_validates_original_hostname_and_separates_shared_ip_hosts(tmp_path):
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
            "/CN=arxiv.org",
            "-addext",
            "subjectAltName=DNS:arxiv.org",
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
        transport = httpx.AsyncHTTPTransport(
            verify=ssl.create_default_context(cafile=str(cert)),
            limits=httpx.Limits(max_keepalive_connections=0),
        )
        transport._pool._network_backend = LocalBackend()
        return transport

    downloader = PDFDownloader(
        ["arxiv.org", "aclanthology.org"], resolver=Resolver(), transport_factory=factory
    )
    try:
        for host, outcome in [("arxiv.org", "downloaded"), ("aclanthology.org", "unavailable")]:
            url = f"https://{host}/paper.pdf"
            result = await downloader.fetch(
                FullTextCandidate(
                    provider="openalex",
                    external_id="W123",
                    source_label="OpenAlex",
                    url=url,
                    location=FullTextLocation(),
                )
            )
            assert result.outcome == outcome
        assert names == ["arxiv.org", "aclanthology.org"]
    finally:
        await downloader.aclose()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
