"""Offline empty runtime for core/e2e startup; never claims real model access."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/ara/capabilities":
            status, body = 200, {"protocol_version": 1, "pull_control": True}
        elif self.path in {"/api/tags", "/api/ps"}:
            status, body = 200, {"models": []}
        elif self.path == "/api/version":
            status, body = 200, {"version": "ara-offline-fixture"}
        else:
            status, body = 404, {"error": "fixture route not found"}
        self.respond(status, body)

    def do_POST(self):
        self.respond(
            503, {"error": "offline fixture: no real model downloads or inference"}
        )

    def respond(self, status, body):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 11434), Handler).serve_forever()
