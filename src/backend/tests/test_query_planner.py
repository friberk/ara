"""Follow-up questions become standalone search queries before retrieval (ARA-077)."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.core.config import Settings
from app.models.research import ChatMessage, GenerationReservation

FOLLOW_UP = "How did it compare to the baselines?"


def turn(question: str, answer: str, citations=()) -> list[ChatMessage]:
    return [
        ChatMessage(role="user", state="completed", content=question, citations=[]),
        ChatMessage(role="assistant", state="completed", content=answer, citations=list(citations)),
    ]


def rag_history() -> list[ChatMessage]:
    chunk = uuid4()
    citation = {"chunk_id": str(chunk), "document_id": str(uuid4()), "page": 3, "excerpt": "RAG"}
    return [
        *turn("Which venue published it?", "It appeared at NeurIPS."),
        *turn("What is the paper's name?", "Sparse Retrieval Revisited."),
        *turn(
            "What does the paper propose?",
            f"It proposes retrieval-augmented generation (RAG) [source:{chunk}].",
            [citation],
        ),
    ]


def plan_output(**fields) -> str:
    plan = {
        "standalone_question": "How did RAG compare to the baselines?",
        "search_queries": ["RAG baselines comparison"],
        "needs_paper_evidence": True,
    }
    return json.dumps({**plan, **fields})


def hosted_fixture(monkeypatch, resources, output):
    """Responses fixture whose answer names the subject only when the history reached it."""
    from app.integrations.llm import HostedLLM
    from app.services import memory
    from tests.test_ai import response_payload

    resources.settings.openai_api_key = SecretStr("fixture")
    requests = []

    def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=response_payload(output(body)))

    monkeypatch.setattr(
        memory,
        "create_llm",
        lambda resources, model, **kwargs: HostedLLM(
            resources.settings,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        ),
    )
    return requests


async def test_given_first_turn_when_planning_then_question_is_the_query_without_a_call(
    monkeypatch,
):
    from app.services import memory

    def no_model(*args, **kwargs):
        raise AssertionError("the first turn must not call a model")

    monkeypatch.setattr(memory, "create_llm", no_model)
    resources = SimpleNamespace(settings=Settings(app_env="test"))
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-luna",
        effort="low",
        history=[],
        memory_summary=None,
        question="What datasets were used?",
    )
    assert plan == memory.QueryPlan(
        standalone_question="What datasets were used?",
        search_queries=["What datasets were used?"],
        needs_paper_evidence=True,
        source="first_turn",
    )


async def test_given_unfinished_first_turn_when_planning_then_it_still_counts_as_first(
    monkeypatch,
):
    from app.services import memory

    monkeypatch.setattr(memory, "create_llm", lambda *args, **kwargs: pytest.fail("no call"))
    history = turn("What datasets?", "")
    history[1].state = "failed"
    resources = SimpleNamespace(settings=Settings(app_env="test"))
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-luna",
        effort="low",
        history=history,
        memory_summary=None,
        question="What datasets were used?",
    )
    assert plan.source == "first_turn"


@pytest.mark.integration
async def test_given_follow_up_on_hosted_chat_when_planning_then_luna_names_the_subject(
    resources, monkeypatch
):
    from app.services import memory

    def output(body):
        subject = "RAG" if "RAG" in json.dumps(body["input"]) else "it"
        return plan_output(
            standalone_question=f"How did {subject} compare to the baselines?",
            search_queries=[f"{subject} baselines comparison", f"{subject} results"],
        )

    requests = hosted_fixture(monkeypatch, resources, output)
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-sol",
        effort="high",
        history=rag_history(),
        memory_summary="User goals: compare retrieval methods.",
        question=FOLLOW_UP,
    )
    assert plan.source == "model"
    assert plan.standalone_question == "How did RAG compare to the baselines?"
    assert plan.search_queries == ["RAG baselines comparison", "RAG results"]
    assert plan.needs_paper_evidence is True
    (body,) = requests
    assert body["model"] == "gpt-5.6-luna" and body["reasoning"] == {"effort": "none"}
    schema = body["text"]["format"]["schema"]
    assert schema["properties"]["search_queries"]["maxItems"] == 3
    assert schema["required"] == ["standalone_question", "search_queries", "needs_paper_evidence"]
    sent = json.dumps(body["input"])
    # The summary and the last two turns, with citations rendered as page references.
    assert "compare retrieval methods" in sent
    assert "Sparse Retrieval Revisited" in sent and "(p. 3)" in sent
    assert "NeurIPS" not in sent and "[source:" not in sent
    assert FOLLOW_UP in sent
    async with resources.sessions() as session:
        reserved = (await session.scalars(select(GenerationReservation.model))).all()
    assert reserved == ["gpt-5.6-luna"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "output",
    [
        "Sure! Here are the queries.",
        plan_output(search_queries=[]),
        plan_output(search_queries=["   "]),
        plan_output(standalone_question=""),
        plan_output(search_queries=["a", "b", "c", "d"]),
        json.dumps({"standalone_question": "RAG?", "search_queries": ["RAG"]}),
    ],
    ids=["prose", "no-queries", "blank-query", "blank-question", "four-queries", "missing-key"],
)
async def test_given_invalid_planner_output_when_planning_then_heuristic_fallback(
    resources, monkeypatch, output
):
    from app.services import memory
    from app.services.retrieval import retrieval_query

    requests = hosted_fixture(monkeypatch, resources, lambda body: output)
    history = rag_history()
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-luna",
        effort="low",
        history=history,
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan == memory.QueryPlan(
        standalone_question=FOLLOW_UP,
        search_queries=[retrieval_query(FOLLOW_UP, history)],
        needs_paper_evidence=True,
        source="fallback",
    )
    assert len(requests) == 1  # a paid call is never retried


@pytest.mark.integration
async def test_given_exhausted_budget_when_planning_then_fallback_without_a_call(
    resources, monkeypatch
):
    from app.services import memory

    requests = hosted_fixture(monkeypatch, resources, lambda body: plan_output())
    resources.settings.llm_daily_budget_usd = 1e-9
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-luna",
        effort="low",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan.source == "fallback" and requests == []


async def install_thinking_model(resources, spec):
    """A ready local model whose verified controls can switch thinking off."""
    from app.models.local_models import ModelInstallation, ModelUse

    async with resources.sessions() as session, session.begin():
        await session.execute(delete(ModelUse))
        await session.execute(delete(ModelInstallation))
        session.add(
            ModelInstallation(
                model_key=spec.key,
                state="ready",
                weights_present=True,
                digest=spec.expected_digest,
                validation={
                    "digest": spec.expected_digest,
                    "context_window": 8192,
                    "runtime_version": "0.40.1-ara.fixture",
                    "reasoning_efforts": ["default", "on", "none"],
                    "thinking_schema": 1,
                    "thinking": {"values": [True, False], "default": True},
                    "think_mapping": {"on": True, "none": False},
                    "supports_streaming": True,
                    "supports_structured_output": True,
                },
            )
        )


def local_fixtures(monkeypatch, resources, reply):
    """Route the local model to an Ollama fixture and trap any hosted client."""
    from app.integrations import llm

    resources.settings.openai_api_key = SecretStr("a hosted key exists but must stay unused")
    local, hosted = [], []

    def ollama(request):
        body = json.loads(request.content)
        local.append(body)
        return reply(body)

    def trap(*args, **kwargs):
        hosted.append(args)
        raise AssertionError("a local chat must never call a hosted model")

    resources.ollama_generation_http = httpx.AsyncClient(transport=httpx.MockTransport(ollama))
    monkeypatch.setattr(llm, "HostedLLM", trap)
    return local, hosted


def ollama_reply(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 90,
            "eval_count": 30,
        },
    )


@pytest.mark.integration
async def test_given_local_chat_when_planning_then_same_model_without_thinking_and_no_hosted(
    resources, monkeypatch
):
    from app.integrations.model_catalog import local_spec
    from app.services import memory

    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, hosted = local_fixtures(monkeypatch, resources, lambda body: ollama_reply(plan_output()))
    plan = await memory.plan_query(
        resources,
        model=spec.key,
        effort="on",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan.source == "model" and plan.search_queries == ["RAG baselines comparison"]
    assert hosted == []
    (body,) = local
    assert body["model"] == spec.model_id and body["think"] is False and body["stream"] is False
    assert body["format"]["properties"]["search_queries"]["minItems"] == 1
    assert "Sparse Retrieval Revisited" in json.dumps(body["messages"])
    async with resources.sessions() as session:
        assert (await session.scalars(select(GenerationReservation))).all() == []


@pytest.mark.integration
async def test_given_local_planner_failure_when_planning_then_fallback_and_no_hosted(
    resources, monkeypatch
):
    from app.integrations.model_catalog import local_spec
    from app.services import memory

    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, hosted = local_fixtures(
        monkeypatch, resources, lambda body: httpx.Response(500, json={"error": "boom"})
    )
    plan = await memory.plan_query(
        resources,
        model=spec.key,
        effort="default",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan.source == "fallback" and len(local) == 1 and hosted == []
