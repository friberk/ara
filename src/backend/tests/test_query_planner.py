"""Follow-up questions become standalone search queries before retrieval (ARA-077)."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.research import ChatMessage, GenerationReservation
from tests.support.models import (
    hosted_responses,
    install_thinking_model,
    local_runtime,
    ollama_reply,
)

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

    requests = hosted_responses(monkeypatch, resources, output)
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

    requests = hosted_responses(monkeypatch, resources, lambda body: output)
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

    requests = hosted_responses(monkeypatch, resources, lambda body: plan_output())
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


@pytest.mark.integration
async def test_given_local_chat_when_planning_then_same_model_without_thinking_and_no_hosted(
    resources, monkeypatch
):
    from app.integrations.model_catalog import local_spec
    from app.services import memory

    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, hosted = await local_runtime(
        monkeypatch, resources, spec, lambda body: ollama_reply(plan_output())
    )
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
    local, hosted = await local_runtime(
        monkeypatch, resources, spec, lambda body: httpx.Response(500, json={"error": "boom"})
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


@pytest.mark.integration
async def test_given_no_hosted_key_when_planning_then_fallback_without_reserving(resources):
    from app.services import memory

    resources.settings.openai_api_key = None
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-luna",
        effort="low",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan.source == "fallback"
    async with resources.sessions() as session:
        assert (await session.scalars(select(GenerationReservation))).all() == []


@pytest.mark.integration
async def test_given_slow_planner_when_planning_then_fallback_after_the_time_limit(
    resources, monkeypatch
):
    import asyncio

    from app.services import memory

    async def slow(body):
        await asyncio.sleep(5)
        return plan_output()

    requests = hosted_responses(monkeypatch, resources, slow)
    monkeypatch.setattr(memory, "PLANNER_TIMEOUT_SECONDS", 0.2)
    started = asyncio.get_running_loop().time()
    plan = await memory.plan_query(
        resources,
        model="gpt-5.6-luna",
        effort="low",
        history=rag_history(),
        memory_summary=None,
        question=FOLLOW_UP,
    )
    assert plan.source == "fallback" and len(requests) == 1
    assert asyncio.get_running_loop().time() - started < 2


@pytest.mark.integration
async def test_given_caller_holds_local_slot_when_planning_then_planner_still_runs(
    resources, monkeypatch
):
    from app.integrations.model_catalog import local_spec
    from app.repositories.local_models import acquire_use, release_use
    from app.services import memory

    spec = local_spec("ifm-k2-horizon-7b")
    await install_thinking_model(resources, spec)
    local, _ = await local_runtime(
        monkeypatch, resources, spec, lambda body: ollama_reply(plan_output())
    )
    # The chat route admits a local answer before preparing it.
    use = await acquire_use(resources.sessions, spec.key)
    try:
        plan = await memory.plan_query(
            resources,
            model=spec.key,
            effort="on",
            history=rag_history(),
            memory_summary=None,
            question=FOLLOW_UP,
        )
    finally:
        await release_use(resources.sessions, use)
    assert plan.source == "model" and len(local) == 1
