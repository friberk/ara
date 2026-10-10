"""A loopback Responses API that answers metadata extraction and records each request (ARA-086).

The hosted client talks to OPENAI_BASE_URL itself, so a real HTTP server on 127.0.0.1 stands in.
"""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic import SecretStr


@asynccontextmanager
async def metadata_model(resources, metadata: dict):
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps(
                {
                    "id": "resp_metadata_fixture",
                    "object": "response",
                    "created_at": 0,
                    "status": "completed",
                    "model": requests[-1].get("model"),
                    "output": [
                        {
                            "id": "msg_metadata",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(metadata),
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    resources.settings.openai_base_url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield requests
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
