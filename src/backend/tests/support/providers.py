"""In-process provider fixtures mirroring tests/fixtures/server.py and ollama_fixture.py."""

import asyncio
import base64
import json
import re
import struct

import httpx

from tests.support.vectors import STOP, WORD, fixture_vector


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


def overlap_relevance(query: str, document: str) -> float:
    """Mirrors the fixtures' reranker relevance: the share of query words in the passage."""
    terms = {w for w in WORD.findall(query.lower()) if w not in STOP}
    words = {w for w in WORD.findall(document.lower()) if w not in STOP}
    return 0.02 + 0.96 * len(terms & words) / max(1, len(terms))


DECISION_INPUT = re.compile(r"Query:\s*(.*?)\n\s*\n(?:Passage|Document)[^:\n]*:\s*(.*)", re.S)


def decisions_fixture(requests, *, delay=0.0, peak=None):
    """Mirrors tests/fixtures/server.py /v1/decisions. `delay` may depend on the input text, and
    `peak[0]` records the most calls in flight."""
    active = 0

    async def handler(request):
        nonlocal active
        requests.append(request)
        body = json.loads(request.content)
        text = body.get("input", "")
        active += 1
        if peak is not None:
            peak[0] = max(peak[0], active)
        try:
            await asyncio.sleep(delay(text) if callable(delay) else delay)
        finally:
            active -= 1
        if "DECISIONS-ERROR-FIXTURE" in text:
            return httpx.Response(500, json={"error": {"message": "Synthetic decisions failure"}})
        match = DECISION_INPUT.search(text)
        answers = []
        for question in body.get("questions", []):
            name = question.get("name", "answer")
            if "REFUSE-FIXTURE" in text:
                answers.append({"type": "refusal", "name": name})
            else:
                probability = overlap_relevance(*match.groups()) if match else 0.5
                answers.append(
                    {"type": "predicate", "name": name, "probability": round(probability, 4)}
                )
        tokens = max(1, len(text.split()))
        return httpx.Response(
            200,
            json={
                "model": body.get("model"),
                "answers": answers,
                "usage": {"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens},
            },
        )

    return httpx.MockTransport(handler)


class OfflineOpenAI(httpx.AsyncBaseTransport):
    """Serves OpenAI requests from the Decisions fixture, so no test reaches the real API;
    every other request passes through unchanged."""

    def __init__(self, base_url: str, requests: list):
        self.base_url = base_url.rstrip("/") + "/"
        self.fixture = decisions_fixture(requests)
        self.network = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        if str(request.url).startswith(self.base_url):
            return await self.fixture.handle_async_request(request)
        return await self.network.handle_async_request(request)

    async def aclose(self) -> None:
        await self.network.aclose()
