"""Streamed chat answers against fixture providers, parsed into SSE events (ARA-073)."""

import asyncio
import json
import re
from types import SimpleNamespace
from uuid import uuid4

import httpx

from tests.test_ai import response_payload

# Passage headers start a line: "[S1] Results · p. 3".
PASSAGE_HANDLE = re.compile(r"^\[(S\d+)\] ", re.M)
CONNECTED = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False))


def first_handle(body: dict) -> str:
    return PASSAGE_HANDLE.findall(body["input"][-1]["content"])[0]


def hosted_stream(calls: list, answer):
    """A Responses stream fixture; `answer(body)` returns the text or a list of deltas."""

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        output = answer(body)
        deltas = [output] if isinstance(output, str) else output
        text = "".join(deltas)
        events = [
            {
                "type": "response.output_text.delta",
                "delta": delta,
                "item_id": "msg",
                "output_index": 0,
                "content_index": 0,
                "sequence_number": index,
            }
            for index, delta in enumerate(deltas)
        ]
        events.append(
            {
                "type": "response.completed",
                "response": response_payload(text),
                "sequence_number": len(deltas),
            }
        )
        wire = "".join("data: " + json.dumps(item) + "\n\n" for item in events)
        return httpx.Response(200, content=wire, headers={"Content-Type": "text/event-stream"})

    return httpx.MockTransport(handler)


def use_hosted(monkeypatch, resources, calls: list, answer) -> None:
    from pydantic import SecretStr

    from app.integrations.llm import HostedLLM
    from app.services import chat

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    monkeypatch.setattr(
        chat,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=hosted_stream(calls, answer)),
        ),
    )


def parse(frames: list[str]) -> list[tuple[str, dict]]:
    events = []
    for frame in frames:
        if frame.startswith("event: "):
            name, data = frame.split("\n", 1)
            events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


async def ask(resources, chat_id, content: str, *, request_id=None, **options):
    """Prepare and stream one question; returns (prepared, events)."""
    from app.schemas.ai import ChatInput
    from app.services import chat

    body = ChatInput(content=content, request_id=request_id or uuid4(), **options)
    prepared = await chat.prepare(resources, chat_id, body)
    frames = [frame async for frame in chat.stream_answer(resources, CONNECTED, prepared)]
    return prepared, parse(frames)


def named(events, name: str) -> list[dict]:
    return [data for event, data in events if event == name]


def offline_answer(monkeypatch, resources, model: str, effort: str):
    """A prepared question whose evidence and memory need no database, for provider tests."""
    from llama_index.core.schema import NodeWithScore, TextNode

    from app.integrations.context_registry import context_profile
    from app.models.research import ChatMessage
    from app.rag.pipeline import EvidenceResult, Scope
    from app.schemas.ai import RetrievalSummary
    from app.services import chat, memory
    from app.services.context import PaperHeader

    document_id = uuid4()
    limits = context_profile(resources, model, effort)
    node = TextNode(
        id_=str(uuid4()),
        text="Results: the blue condition reached 87 percent accuracy.",
        metadata={
            "page": 2,
            "page_end": 2,
            "section": "Results",
            "kind": "text",
            "ordinal": 0,
            "document_id": str(document_id),
        },
    )

    async def retrieve(resources, **options):
        summary = RetrievalSummary(mode="keyword", search_queries=options["queries"])
        return EvidenceResult([], summary, {}, [NodeWithScore(node=node)], {}, limits.counter)

    async def record(*args):
        return None

    async def remembered(resources, chat_id, history):
        return memory.AnswerMemory(None, history)

    monkeypatch.setattr(chat, "retrieve_evidence", retrieve)
    monkeypatch.setattr(chat, "record_evidence", record)
    monkeypatch.setattr(memory, "answer_memory", remembered)
    monkeypatch.setattr(memory, "remember_turn", record)
    assistant = ChatMessage(id=uuid4(), model=model, reasoning_effort=effort)
    return chat.Prepared(
        assistant,
        replay=False,
        question="What accuracy?",
        scopes=[Scope(document_id, "offline")],
        retrieval_profile="openai-3-large",
        papers=[PaperHeader(title="Offline paper", authors=[], year=None)],
        limits=limits,
        evidence_budget=limits.input_budget // 2,
    )
