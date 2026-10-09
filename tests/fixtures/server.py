"""Deterministic external HTTP services. Used only by the isolated test stack."""

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ollama_fixture import OllamaFixture

OLLAMA = OllamaFixture()

TITLE = "Traceable Research Systems"
ABSTRACT = (
    "A synthetic evaluation of a retrieval-first research assistant using the Orion-12 dataset."
)
DOI = "10.5555/cs593.fixture"
SOURCE_ID = "11111111-1111-4111-8111-111111111111"


def semantic_paper():
    return {
        "paperId": "fixture-paper-1",
        "title": TITLE,
        "authors": [{"authorId": "fixture-author", "name": "Ada Researcher"}],
        "year": 2024,
        "abstract": ABSTRACT,
        "externalIds": {"DOI": DOI},
        "url": "https://example.org/synthetic-research-fixture",
        "openAccessPdf": None,
    }


def openalex_paper():
    inverted = {}
    for position, word in enumerate(ABSTRACT.split()):
        inverted.setdefault(word, []).append(position)
    return {
        "id": "https://openalex.org/W123456789",
        "title": TITLE,
        "display_name": TITLE,
        "publication_year": 2024,
        "doi": "https://doi.org/" + DOI,
        "authorships": [
            {
                "author": {
                    "id": "https://openalex.org/A123",
                    "display_name": "Ada Researcher",
                }
            }
        ],
        "abstract_inverted_index": inverted,
        "primary_location": {
            "landing_page_url": "https://example.org/synthetic-research-fixture",
            "pdf_url": None,
            "is_oa": False,
        },
        "best_oa_location": None,
        "locations": [],
        "ids": {"doi": "https://doi.org/" + DOI},
    }


def structured_value(schema, root, field=""):
    if "$ref" in schema:
        return structured_value(
            root.get("$defs", {}).get(schema["$ref"].rsplit("/", 1)[-1], {}),
            root,
            field,
        )
    if "anyOf" in schema:
        branch = next((b for b in schema["anyOf"] if b.get("type") != "null"), {})
        return structured_value(branch, root, field)
    if "enum" in schema:
        return schema["enum"][0]
    if schema.get("type") == "object":
        return {
            name: structured_value(value, root, name)
            for name, value in schema.get("properties", {}).items()
        }
    if schema.get("type") == "array":
        return ["Ada Researcher"] if field == "authors" else []
    if schema.get("type") == "integer":
        return 2024 if field in ("year", "publication_year") else 1
    if schema.get("type") == "number":
        return 1.0
    if schema.get("type") == "boolean":
        return True
    if schema.get("type") == "null":
        return None
    return {"title": TITLE, "abstract": ABSTRACT, "doi": DOI}.get(field, "Synthetic fixture")


def response_payload(model, text, status="completed"):
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 1720000000,
        "status": status,
        "error": None,
        "incomplete_details": None,
        "model": model,
        "output": [
            {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ]
        if status == "completed"
        else [],
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 80,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 180,
        },
        "metadata": {},
        "parallel_tool_calls": False,
        "store": False,
        "tools": [],
        "tool_choice": "auto",
        "reasoning": {"effort": "low", "summary": None},
        "text": {"format": {"type": "text"}},
        "truncation": "disabled",
        "temperature": 1,
        "top_p": 1,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if OLLAMA.get(self, parsed.path):
            return
        if parsed.path == "/health":
            self.send_json({"status": "ok"})
        elif parsed.path == "/graph/v1/paper/search":
            text = query.get("query", [""])[0]
            if text == "rate-limit":
                self.send_json({"message": "Synthetic provider rate limit"}, 429)
            else:
                offset = int(query.get("offset", ["0"])[0])
                self.send_json(
                    {
                        "total": 0 if text == "empty" else 1,
                        "offset": offset,
                        "data": [] if text == "empty" or offset else [semantic_paper()],
                    }
                )
        elif parsed.path.startswith("/graph/v1/paper/"):
            self.send_json(semantic_paper())
        elif parsed.path == "/works":
            text = query.get("search", [""])[0]
            self.send_json(
                {
                    "meta": {"count": 0 if text == "empty" else 1, "next_cursor": None},
                    "results": [] if text == "empty" else [openalex_paper()],
                }
            )
        elif parsed.path.startswith("/works/"):
            self.send_json(openalex_paper())
        elif parsed.path in ("/v1/models", "/v1/models/"):
            self.send_json(
                {
                    "object": "list",
                    "data": [
                        {
                            "id": model,
                            "object": "model",
                            "created": 0,
                            "owned_by": "fixture",
                        }
                        for model in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
                    ],
                }
            )
        else:
            self.send_json({"error": "Unknown fixture endpoint"}, 404)

    def do_POST(self):
        if urlparse(self.path).path.startswith("/api/"):
            self.ollama_mutation()
            return
        if urlparse(self.path).path != "/v1/responses":
            self.send_json({"error": "Unknown fixture endpoint"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            self.send_json({"error": "Fixture request too large"}, 413)
            return
        try:
            request = json.loads(self.rfile.read(length))
        except (ValueError, TypeError):
            self.send_json({"error": "Invalid JSON"}, 400)
            return
        model = request.get("model", "gpt-5.6-luna")
        schema = request.get("text", {}).get("format", {}).get("schema")
        if schema:
            answer = json.dumps(structured_value(schema, schema))
        else:
            inputs = json.dumps(request.get("input", ""))
            sources = list(dict.fromkeys(re.findall(r"source:([0-9a-fA-F-]{36})", inputs)))
            citation = f" [source:{sources[0]}]" if sources else ""
            answer = (
                "The paper evaluates a retrieval-first pipeline on the Orion-12 dataset. "
                "The reported accuracy is 86 percent; "
                "the experiment contains only twelve examples. "
                + citation
                + "\n\nIts main limitation is the small synthetic dataset, "
                "so these results do not establish performance on real research libraries."
                + citation
            )
        if not request.get("stream"):
            self.send_json(response_payload(model, answer))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        sequence = 0

        def emit(kind, data):
            nonlocal sequence
            sequence += 1
            data = {"type": kind, "sequence_number": sequence, **data}
            self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()

        try:
            emit(
                "response.created",
                {"response": response_payload(model, "", "in_progress")},
            )
            for start in range(0, len(answer), 35):
                emit(
                    "response.output_text.delta",
                    {
                        "item_id": "msg_fixture",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": answer[start : start + 35],
                        "logprobs": [],
                    },
                )
                time.sleep(0.025)
            emit(
                "response.output_text.done",
                {
                    "item_id": "msg_fixture",
                    "output_index": 0,
                    "content_index": 0,
                    "text": answer,
                    "logprobs": [],
                },
            )
            emit("response.completed", {"response": response_payload(model, answer)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    def do_DELETE(self):
        self.ollama_mutation()

    def ollama_mutation(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            self.send_json({"error": "Fixture request too large"}, 413)
            return
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except (ValueError, TypeError):
            self.send_json({"error": "Invalid JSON"}, 400)
            return
        if not OLLAMA.mutate(self, urlparse(self.path).path, body, structured_value):
            self.send_json({"error": "Unknown fixture endpoint"}, 404)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
