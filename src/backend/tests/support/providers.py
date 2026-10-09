"""In-process provider fixtures mirroring tests/fixtures/server.py and ollama_fixture.py."""

import base64
import json
import struct

import httpx

from tests.support.vectors import fixture_vector


def openai_fixture(requests, *, status=200):
    """Mirrors tests/fixtures/server.py /v1/embeddings, including base64 encoding."""

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "fixture failure"}})
        dims = body.get("dimensions") or 3072
        data = []
        for index, text in enumerate(body["input"]):
            vector = fixture_vector(text, dims)
            if body.get("encoding_format", "base64") == "base64":
                vector = base64.b64encode(struct.pack(f"<{dims}f", *vector)).decode()
            data.append({"object": "embedding", "index": index, "embedding": vector})
        tokens = sum(len(text.split()) for text in body["input"])
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": data,
                "model": body["model"],
                "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
            },
        )

    return httpx.MockTransport(handler)


def ollama_fixture(requests):
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        texts = [body["input"]] if isinstance(body["input"], str) else body["input"]
        return httpx.Response(
            200, json={"embeddings": [fixture_vector(text, 2560) for text in texts]}
        )

    return httpx.MockTransport(handler)
