"""Small windows: a comparison that needs more than E reads each paper, then synthesises (ARA-094).

Every hosted model has a 1M window today, so this runs on a synthetic 16K catalog entry
(docs/plans/retrieval-orchestration.md, "Window sizes": local 16K -> map-reduce).
"""

import json
import re
from dataclasses import replace

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.tokens import PromptMessage, count_messages
from tests.support.answers import ask, named
from tests.support.chats import new_chat
from tests.support.evidence import seed_structured
from tests.test_ai import response_payload

pytestmark = pytest.mark.integration

MODEL, EFFORT = "synthetic-16384", "low"
QUESTION = "Compare how the two papers measure retrieval recall."
HANDLE = re.compile(r"\[(S\d+)\]")
BODY = "The {name} study measures retrieval recall at ten passages on the benchmark. " * 40


def sections(name: str) -> list[tuple]:
    """Ten passages of about 600 tokens, each about recall, so both papers compete."""
    return [(f"{n} Results", "text", n + 1, n + 1, BODY.format(name=name)) for n in range(10)]


@pytest.fixture
def small_window(monkeypatch):
    from app.integrations import hosted_catalog

    luna = hosted_catalog.HOSTED_MODELS["gpt-5.6-luna"]
    entry = replace(luna, key=MODEL, window=16_384)
    monkeypatch.setitem(hosted_catalog.HOSTED_MODELS, MODEL, entry)
    return entry


def sent(counter, body: dict) -> int:
    messages = [PromptMessage("system", body["instructions"])] + [
        PromptMessage(item["role"], item["content"]) for item in body["input"]
    ]
    return count_messages(counter, messages)


def responses(calls: list):
    """Map calls are plain responses citing two passages; the synthesis streams and cites every
    handle in the notes it was shown."""

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        shown = HANDLE.findall(body["input"][-1]["content"])
        cited = shown if body.get("stream") else shown[:2]
        text = "Recall is measured at ten passages " + "".join(f"[{h}]" for h in cited)
        if not body.get("stream"):
            return httpx.Response(200, json=response_payload(text))
        events = [
            {
                "type": "response.output_text.delta",
                "delta": text,
                "item_id": "msg",
                "output_index": 0,
                "content_index": 0,
                "sequence_number": 0,
            },
            {
                "type": "response.completed",
                "response": response_payload(text),
                "sequence_number": 1,
            },
        ]
        wire = "".join("data: " + json.dumps(item) + "\n\n" for item in events)
        return httpx.Response(200, content=wire, headers={"Content-Type": "text/event-stream"})

    return httpx.MockTransport(handler)


async def test_given_a_16k_window_and_a_comparison_when_answering_then_each_paper_is_read_apart(
    resources, monkeypatch, small_window
):
    from app.integrations.context_registry import hosted_profile
    from app.integrations.llm import HostedLLM
    from app.services import chat
    from tests.support.models import hosted_responses

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    seeded = [
        await seed_structured(
            resources, title=f"{name} Recall Study", sections=sections(name), profile=None
        )
        for name in ("Sparse", "Dense")
    ]
    chat_id = await new_chat(resources, *[(paper, document) for paper, document, _ in seeded])
    plan = {
        "standalone_question": QUESTION,
        "search_queries": ["retrieval recall ten passages"],
        "needs_paper_evidence": True,
        "sub_questions": [
            {"paper": 1, "question": "How does the Sparse study measure recall?"},
            {"paper": 2, "question": "How does the Dense study measure recall?"},
        ],
        "question_type": "comparative",
    }
    hosted_responses(monkeypatch, resources, lambda body: json.dumps(plan))
    calls = []
    monkeypatch.setattr(
        chat,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings, http_client=httpx.AsyncClient(transport=responses(calls))
        ),
    )
    prepared, events = await ask(resources, chat_id, QUESTION, model=MODEL, reasoning_effort=EFFORT)
    (completed,) = named(events, "message.completed")

    profile = hosted_profile(MODEL, EFFORT)
    *maps, synthesis = calls
    # One call per paper, then the synthesis; every call fits the working budget W.
    assert len(maps) == 2 and synthesis.get("stream") is True
    assert all(sent(profile.counter, body) <= profile.input_budget for body in calls)
    titles = [body["instructions"] for body in maps]
    assert any("Sparse Recall Study" in text for text in titles)
    assert any("Dense Recall Study" in text for text in titles)
    # The synthesis sees each paper's notes, not its passages.
    assert "Recall is measured at ten passages" in synthesis["input"][-1]["content"]
    assert "measures retrieval recall at ten passages" not in synthesis["input"][-1]["content"]
    cited = {item["document_id"] for item in completed["citations"]}
    assert cited == {str(document) for _, document, _ in seeded}
    assert completed["retrieval"]["map_reduce"] is True
    async with resources.sessions() as session:
        from app.models.research import ChatMessage

        row = await session.get(ChatMessage, prepared.assistant.id)
    assert len(row.retrieval["billed"]["map"]) == 2
    from app.services.costs import Spend, message_spend

    spend, alone = Spend(), Spend()
    message_spend(spend, row.state, row.model, row.usage, row.retrieval["billed"])
    message_spend(alone, row.state, row.model, row.usage, {})
    assert spend.answers > alone.answers


async def test_given_a_large_window_when_comparing_the_same_papers_then_one_call_answers(
    resources, monkeypatch
):
    from app.integrations.llm import HostedLLM
    from app.services import chat
    from tests.support.models import hosted_responses

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    seeded = [
        await seed_structured(
            resources, title=f"{name} Recall Study", sections=sections(name), profile=None
        )
        for name in ("Sparse", "Dense")
    ]
    chat_id = await new_chat(resources, *[(paper, document) for paper, document, _ in seeded])
    plan = {
        "standalone_question": QUESTION,
        "search_queries": ["retrieval recall ten passages"],
        "needs_paper_evidence": True,
        "sub_questions": [],
        "question_type": "comparative",
    }
    hosted_responses(monkeypatch, resources, lambda body: json.dumps(plan))
    calls = []
    monkeypatch.setattr(
        chat,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings, http_client=httpx.AsyncClient(transport=responses(calls))
        ),
    )
    _, events = await ask(
        resources, chat_id, QUESTION, model="gpt-5.6-luna", reasoning_effort=EFFORT
    )
    (completed,) = named(events, "message.completed")
    assert len(calls) == 1
    assert completed["retrieval"]["map_reduce"] is False


async def test_given_a_16k_window_when_the_retry_wants_more_than_e_then_it_reads_each_paper(
    resources, monkeypatch, small_window
):
    """A lookup over two papers fits E in one call; its retry wants twice the first pass, more
    than E, so the retry reads each paper apart before answering."""
    from app.integrations.llm import HostedLLM
    from app.services import chat
    from tests.support.models import hosted_responses

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    seeded = [
        await seed_structured(
            resources, title=f"{name} Recall Study", sections=sections(name), profile=None
        )
        for name in ("Sparse", "Dense")
    ]
    chat_id = await new_chat(resources, *[(paper, document) for paper, document, _ in seeded])
    plan = {
        "standalone_question": "What recall at ten passages is reported?",
        "search_queries": ["retrieval recall ten passages"],
        "needs_paper_evidence": True,
        "sub_questions": [],
        "question_type": "lookup",
    }
    hosted_responses(monkeypatch, resources, lambda body: json.dumps(plan))
    calls = []
    answer = responses(calls)

    async def first_insufficient(request):
        if json.loads(request.content).get("stream") and not any(c.get("stream") for c in calls):
            calls.append(json.loads(request.content))
            text = "[insufficient-evidence] No figure is given."
            events = [
                {
                    "type": "response.output_text.delta",
                    "delta": text,
                    "item_id": "msg",
                    "output_index": 0,
                    "content_index": 0,
                    "sequence_number": 0,
                },
                {
                    "type": "response.completed",
                    "response": response_payload(text),
                    "sequence_number": 1,
                },
            ]
            wire = "".join("data: " + json.dumps(item) + "\n\n" for item in events)
            return httpx.Response(200, content=wire, headers={"Content-Type": "text/event-stream"})
        return await answer.handle_async_request(request)

    monkeypatch.setattr(
        chat,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(first_insufficient)),
        ),
    )
    _, events = await ask(
        resources, chat_id, "What recall is reported?", model=MODEL, reasoning_effort=EFFORT
    )
    (completed,) = named(events, "message.completed")
    streams = [body for body in calls if body.get("stream")]
    maps = [body for body in calls if not body.get("stream")]
    assert len(streams) == 2 and len(maps) == 2
    assert completed["retrieval"]["retried"] is True
    assert completed["retrieval"]["map_reduce"] is True
    assert completed["grounding"] == "supported"
    stages = [data["stage"] for data in named(events, "message.status")]
    assert stages.index("widening") < stages.index("mapping")
