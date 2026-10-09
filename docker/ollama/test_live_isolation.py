#!/usr/bin/env python3
"""Exercise real inference while an independent synthetic-registry pull is paused.

Requires a patched runtime already holding the authorized 7B model. The local
registry serves synthetic bytes, not another downloaded model. Docker Desktop
can reach this host fixture through host.docker.internal.
"""

import argparse
import hashlib
import json
import threading
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "hf.co/IFM/K2-Horizon-7B-GGUF:Q4_K_M"


def verify(base):
    body = b"ara-independent-transfer" * 500000
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    started = threading.Event()
    canceled = threading.Event()
    transferred = [0]

    class Registry(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()

        def do_GET(self):
            if "/manifests/" in self.path:
                encoded = json.dumps(
                    {
                        "schemaVersion": 2,
                        "layers": [
                            {
                                "digest": digest,
                                "size": len(body),
                                "mediaType": "application/vnd.ollama.image.model",
                            }
                        ],
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            elif "/blobs/" in self.path:
                self.send_response(200)
                self.send_header(
                    "Location",
                    f"http://host.docker.internal:{self.server.server_port}/data",
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                begin, end = map(
                    int, self.headers["Range"].removeprefix("bytes=").split("-")
                )
                self.send_response(206)
                self.send_header("Content-Length", str(end - begin + 1))
                self.end_headers()
                try:
                    for position in range(begin, end + 1, 32768):
                        chunk = body[position : min(position + 32768, end + 1)]
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        transferred[0] += len(chunk)
                        if transferred[0] >= 262144:
                            started.set()
                        time.sleep(0.01)
                except (BrokenPipeError, ConnectionResetError):
                    canceled.set()

        def log_message(self, *_args):
            pass

    registry = ThreadingHTTPServer(("0.0.0.0", 0), Registry)
    threading.Thread(target=registry.serve_forever, daemon=True).start()

    def post(path, value):
        req = urllib.request.Request(
            base + path,
            json.dumps(value).encode(),
            {"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=900) as response:
            return response.read()

    operation = str(uuid.uuid4())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pull = pool.submit(
                post,
                "/api/ara/pull",
                {
                    "model": f"http://host.docker.internal:{registry.server_port}/library/isolation:latest",
                    "operation_id": operation,
                    "insecure": True,
                },
            )
            if not started.wait(10):
                raise AssertionError("synthetic transfer did not start")
            chat = pool.submit(
                post,
                "/api/chat",
                {
                    "model": MODEL,
                    "messages": [{"role": "user", "content": "What is 3 + 3?"}],
                    "stream": True,
                    "think": False,
                    "options": {
                        "num_ctx": 8192,
                        "num_predict": 2048,
                        "num_thread": 4,
                        "temperature": 0,
                    },
                },
            )
            time.sleep(0.1)
            start = time.monotonic()
            ack = json.loads(post(f"/api/ara/pulls/{operation}/pause", {}))
            latency = time.monotonic() - start
            assert ack == {"state": "paused"}, ack
            pull.result(timeout=2)
            assert canceled.wait(2), "registry transfer did not close after pause"
            count = transferred[0]
            time.sleep(0.2)
            assert transferred[0] == count, "bytes advanced after acknowledgment"
            events = [json.loads(line) for line in chat.result().splitlines()]
            answer = "".join(e.get("message", {}).get("content", "") for e in events)
            assert events[-1].get("done_reason") == "stop", events[-1]
            assert "6" in answer or "six" in answer.lower(), answer
            return {
                "pause_ack_seconds": latency,
                "transferred_bytes_at_ack": count,
                "concurrent_final_answer": answer,
                "final_metrics": events[-1],
            }
    finally:
        registry.shutdown()
        registry.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:11435")
    args = parser.parse_args()
    print(json.dumps(verify(args.base), indent=2))
