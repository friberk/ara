"""Catalog rerankers over real budget and admission state, with in-process providers (ARA-074)."""

import asyncio
import json
import math
import re
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.integrations.model_catalog import local_spec
from app.integrations.reranker_catalog import RELEVANCE_INSTRUCTIONS, RERANKERS
from app.models.local_models import ModelInstallation, ModelUse
from app.models.research import GenerationReservation
from tests.support.nodes import node
from tests.support.providers import decisions_fixture, overlap_relevance

pytestmark = pytest.mark.integration
OPENAI, LOCAL = "openai-gpt-6-luna", "qwen3-rerank-0.6b"
# Windows and concurrency are catalog data; tests read them rather than pinning numbers.
HOSTED, ON_DEVICE = RERANKERS[OPENAI], RERANKERS[LOCAL]
QUERY = "What recall does BM25 reach on the benchmark?"
IRRELEVANT = "Proteins fold in yeast cells under heat stress."
RELEVANT = "BM25 reaches recall 0.61 on the benchmark."  # 0.74 by word overlap
PARTIAL = "Recall is reported per benchmark."  # 0.50
RERANK = re.compile(r"<Query>: (.*?)\n<Document>: (.*?)<\|im_end\|>", re.S)


async def use_transport(resources, transport):
    await resources.http.aclose()
    resources.http = httpx.AsyncClient(transport=transport)


async def hosted(resources, requests, **options):
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    await use_transport(resources, decisions_fixture(requests, **options))
    return resources


def ids(nodes):
    return [item.node.node_id for item in nodes]


async def reservations(resources):
    async with resources.sessions() as session:
        return (await session.scalars(select(GenerationReservation))).all()


async def test_given_decisions_reranker_when_reranking_then_relevance_orders_candidates(
    resources,
):
    from app.rag.rerank import rerank_candidates

    requests = []
    nodes = [node(1, IRRELEVANT), node(2, RELEVANT), node(3, PARTIAL)]
    outcome = await rerank_candidates(
        await hosted(resources, requests), query=QUERY, nodes=nodes, reranker=OPENAI
    )
    assert ids(outcome.nodes) == ids([nodes[1], nodes[2], nodes[0]])
    assert (outcome.reranked, outcome.reranker, outcome.skipped) == (True, OPENAI, None)
    assert outcome.scores == {
        nodes[0].node.node_id: 0.02,
        nodes[1].node.node_id: 0.74,
        nodes[2].node.node_id: 0.5,
    }
    assert outcome.elapsed_ms >= 0
    assert len(requests) == 3
    for request in requests:
        assert request.url.path == "/v1/decisions"
        assert request.headers["authorization"] == "Bearer http-fixture-only"
        assert request.extensions["timeout"]["read"] <= 15
    sent = {
        json.loads(request.content)["input"]: json.loads(request.content) for request in requests
    }
    assert sent[f"Query:\n{QUERY}\n\nPassage (Results · p. 3):\n{IRRELEVANT}"] == {
        "model": "gpt-6-luna",
        "input": f"Query:\n{QUERY}\n\nPassage (Results · p. 3):\n{IRRELEVANT}",
        "questions": [
            {"type": "predicate", "name": "relevance", "instructions": RELEVANCE_INSTRUCTIONS}
        ],
    }
    (reservation,) = await reservations(resources)
    assert reservation.model == f"rerank:{OPENAI}"
    assert Decimal(0) < reservation.amount < Decimal("0.001")


async def test_given_more_fused_nodes_than_candidates_when_reranking_then_the_tail_is_unchanged(
    resources,
):
    from app.rag.rerank import rerank_candidates

    requests, window = [], HOSTED.candidates
    nodes = [node(index, f"{IRRELEVANT} Sample {index}.") for index in range(1, window + 1)]
    nodes[4] = node(5, RELEVANT)
    nodes += [node(window + 1, RELEVANT), node(window + 2, RELEVANT)]
    outcome = await rerank_candidates(
        await hosted(resources, requests), query=QUERY, nodes=nodes, reranker=OPENAI
    )
    assert len(requests) == window and len(outcome.scores) == window
    assert ids(outcome.nodes) == ids([nodes[4], *nodes[:4], *nodes[5:]])


async def test_given_tied_scores_when_reranking_then_fused_rank_breaks_ties(resources):
    from app.rag.rerank import rerank_candidates

    # The earliest tied candidate answers last, so completion order cannot be relied on.
    requests = []
    nodes = [
        node(1, IRRELEVANT),
        node(2, "BM25 recall reach benchmark alpha"),
        node(3, "BM25 recall reach benchmark beta"),
        node(4, "BM25 recall reach benchmark gamma"),
    ]
    await hosted(resources, requests, delay=lambda text: 0.05 if "alpha" in text else 0)
    outcome = await rerank_candidates(resources, query=QUERY, nodes=nodes, reranker=OPENAI)
    assert ids(outcome.nodes) == ids([nodes[1], nodes[2], nodes[3], nodes[0]])
    assert outcome.scores[nodes[1].node.node_id] == outcome.scores[nodes[3].node.node_id]


async def test_given_refusal_and_server_error_when_reranking_then_the_scored_subset_is_reranked(
    resources,
):
    from app.rag.rerank import rerank_candidates

    requests = []
    nodes = [
        node(1, "BM25 recall REFUSE-FIXTURE"),
        node(2, IRRELEVANT),
        node(3, "DECISIONS-ERROR-FIXTURE BM25 recall"),
        node(4, RELEVANT),
    ]
    outcome = await rerank_candidates(
        await hosted(resources, requests), query=QUERY, nodes=nodes, reranker=OPENAI
    )
    assert ids(outcome.nodes) == ids([nodes[3], nodes[1], nodes[0], nodes[2]])
    assert (outcome.reranked, outcome.skipped) == (True, None)
    assert set(outcome.scores) == {nodes[1].node.node_id, nodes[3].node.node_id}
    assert len(requests) == 4  # a failed paid call is never retried


async def test_given_every_call_fails_when_reranking_then_fusion_order_is_kept(resources):
    from app.rag.rerank import rerank_candidates

    requests = []
    nodes = [node(1, "DECISIONS-ERROR-FIXTURE one"), node(2, "DECISIONS-ERROR-FIXTURE two")]
    outcome = await rerank_candidates(
        await hosted(resources, requests), query=QUERY, nodes=nodes, reranker=OPENAI
    )
    assert (outcome.nodes, outcome.reranked, outcome.reranker) == (nodes, False, OPENAI)
    assert outcome.skipped == "RERANKER_FAILED" and outcome.scores == {}
    assert len(requests) == 2


async def test_given_spent_daily_budget_when_reranking_then_no_request_is_sent(resources):
    from app.rag.rerank import rerank_candidates

    cap = Decimal(str(resources.settings.llm_daily_budget_usd))
    async with resources.sessions() as session, session.begin():
        session.add(GenerationReservation(model="gpt-5.6-luna", amount=cap))
    requests = []
    nodes = [node(1, IRRELEVANT), node(2, RELEVANT)]
    outcome = await rerank_candidates(
        await hosted(resources, requests), query=QUERY, nodes=nodes, reranker=OPENAI
    )
    assert (outcome.nodes, outcome.reranked, outcome.skipped) == (
        nodes,
        False,
        "DAILY_BUDGET_EXCEEDED",
    )
    assert requests == []
    assert [row.model for row in await reservations(resources)] == ["gpt-5.6-luna"]


async def test_given_many_candidates_when_reranking_then_concurrency_is_bounded(resources):
    from app.rag.rerank import rerank_candidates

    requests, peak = [], [0]
    nodes = [node(index, f"{PARTIAL} {index}") for index in range(1, HOSTED.candidates + 1)]
    await hosted(resources, requests, delay=0.02, peak=peak)
    outcome = await rerank_candidates(resources, query=QUERY, nodes=nodes, reranker=OPENAI)
    assert len(requests) == HOSTED.candidates and len(outcome.scores) == HOSTED.candidates
    assert peak[0] == min(HOSTED.concurrency, HOSTED.candidates)


def logprobs(p_yes: float) -> dict:
    return {
        "response": "yes" if p_yes >= 0.5 else "no",
        "done": True,
        "done_reason": "length",
        "logprobs": [
            {
                "token": "yes" if p_yes >= 0.5 else "no",
                "logprob": math.log(max(p_yes, 1 - p_yes)),
                "top_logprobs": [
                    {"token": "yes", "logprob": math.log(p_yes)},
                    {"token": "no", "logprob": math.log(1 - p_yes)},
                ],
            }
        ],
    }


async def local_runtime(resources, requests, *, held=None, peak=None, fail_on=None, delay=0.0):
    """Inventory, version and raw-template scoring for the pinned local reranker."""
    spec = local_spec("qwen3-reranker-0.6b")
    active = 0

    async def handler(request):
        nonlocal active
        if request.url.path == "/api/tags":
            item = {"name": spec.model_id, "model": spec.model_id, "digest": spec.expected_digest}
            return httpx.Response(200, json={"models": [item]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.1-ara.fixture"})
        if request.url.path != "/api/generate":
            return httpx.Response(404, json={"error": "unexpected request"})
        requests.append(request)
        if fail_on is not None and len(requests) == fail_on:
            raise httpx.ConnectError("runtime stopped")
        active += 1
        if peak is not None:
            peak[0] = max(peak[0], active)
        try:
            await asyncio.sleep(delay)
            if held is not None:
                async with resources.sessions() as session:
                    uses = (await session.scalars(select(ModelUse))).all()
                held.append([(use.slot, use.model_key) for use in uses])
        finally:
            active -= 1
        query, document = RERANK.search(json.loads(request.content)["prompt"]).groups()
        return httpx.Response(200, json=logprobs(overlap_relevance(query, document)))

    await use_transport(resources, httpx.MockTransport(handler))
    return spec


async def install(resources, spec):
    async with resources.sessions() as session, session.begin():
        session.add(
            ModelInstallation(
                model_key=spec.key,
                state="ready",
                weights_present=True,
                digest=spec.expected_digest,
                validation={
                    "kind": "reranker",
                    "digest": spec.expected_digest,
                    "context_window": resources.settings.ollama_context_window,
                    "runtime_version": "0.40.1-ara.fixture",
                    "thinking_schema": 1,
                },
            )
        )


async def test_given_local_reranker_when_reranking_then_scoring_is_sequential_and_admitted(
    resources,
):
    from app.rag.rerank import rerank_candidates

    requests, held, peak = [], [], [0]
    spec = await local_runtime(resources, requests, held=held, peak=peak)
    await install(resources, spec)
    window = ON_DEVICE.candidates
    nodes = [node(1, IRRELEVANT), node(2, RELEVANT), node(3, PARTIAL)]
    nodes += [node(index, f"{IRRELEVANT} Sample {index}.") for index in range(4, window + 1)]
    nodes += [node(window + 1, RELEVANT), node(window + 2, RELEVANT)]
    outcome = await rerank_candidates(resources, query=QUERY, nodes=nodes, reranker=LOCAL)
    assert ids(outcome.nodes) == ids([nodes[1], nodes[2], nodes[0], *nodes[3:]])
    assert (outcome.reranked, outcome.reranker, outcome.skipped) == (True, LOCAL, None)
    assert math.isclose(outcome.scores[nodes[1].node.node_id], 0.74)
    assert len(requests) == window and len(outcome.scores) == window
    assert peak[0] == 1  # local scoring is sequential whatever the catalog says
    assert held == [[("retrieval", spec.key)]] * window
    for request in requests:
        body = json.loads(request.content)
        assert body["model"] == spec.model_id
        assert (body["raw"], body["stream"], body["logprobs"]) == (True, False, True)
        assert body["top_logprobs"] == 20 and body["keep_alive"] == "10m"
        assert body["options"] == {
            "temperature": 0,
            "num_predict": 1,
            "num_ctx": 2048,
            "num_thread": resources.settings.ollama_num_threads,
        }
        assert request.extensions["timeout"]["read"] <= 60
    async with resources.sessions() as session:
        assert (await session.scalars(select(ModelUse))).all() == []


async def test_given_long_inputs_when_reranking_locally_then_the_prompt_fits_the_context(
    resources,
):
    from app.integrations.tokens import TiktokenCounter
    from app.rag.rerank import rerank_candidates

    requests = []
    await install(resources, await local_runtime(resources, requests))
    document = "Recall " + " ".join(f"passage{index}" for index in range(4000))
    query = "BM25 recall " + " ".join(f"word{index}" for index in range(600))
    outcome = await rerank_candidates(
        resources, query=query, nodes=[node(1, document)], reranker=LOCAL
    )
    assert outcome.reranked is True
    counter = TiktokenCounter("o200k_base", resources.settings.local_token_factor)
    prompt = json.loads(requests[0].content)["prompt"]
    sent_query, sent_document = RERANK.search(prompt).groups()
    assert document.startswith(sent_document) and counter.count(sent_document) <= 1800
    assert query.startswith(sent_query) and counter.count(sent_query) <= 128
    assert counter.count(prompt) < 2048


async def test_given_uninstalled_local_reranker_when_reranking_then_it_is_skipped(resources):
    from app.rag.rerank import rerank_candidates

    requests = []
    await local_runtime(resources, requests)
    nodes = [node(1, IRRELEVANT), node(2, RELEVANT)]
    outcome = await rerank_candidates(resources, query=QUERY, nodes=nodes, reranker=LOCAL)
    assert (outcome.nodes, outcome.reranked, outcome.reranker) == (nodes, False, LOCAL)
    assert outcome.skipped == "LOCAL_MODEL_NOT_READY" and requests == []


async def test_given_runtime_lost_mid_rerank_when_reranking_then_scoring_stops(resources):
    from app.rag.rerank import rerank_candidates

    requests = []
    await install(resources, await local_runtime(resources, requests, fail_on=2))
    nodes = [node(1, IRRELEVANT), node(2, PARTIAL), node(3, RELEVANT), node(4, RELEVANT)]
    outcome = await rerank_candidates(resources, query=QUERY, nodes=nodes, reranker=LOCAL)
    assert len(requests) == 2  # the runtime is gone: no more 30-second waits
    assert (outcome.reranked, outcome.skipped) == (True, None)
    assert outcome.scores == {nodes[0].node.node_id: pytest.approx(0.02)}
    assert ids(outcome.nodes) == ids(nodes)


async def test_given_slow_local_reranker_when_the_deadline_passes_then_fusion_order_is_kept(
    resources, monkeypatch
):
    """Each call may take 30 s, so 12 slow calls once delayed an answer by about 6 minutes."""
    from app.rag import rerank
    from app.rag.rerank import rerank_candidates

    monkeypatch.setattr(rerank, "LOCAL_DEADLINE_SECONDS", 0.5, raising=False)
    requests = []
    await install(resources, await local_runtime(resources, requests, delay=0.25))
    nodes = [node(1, IRRELEVANT), node(2, PARTIAL), node(3, RELEVANT)]
    nodes += [node(index, f"{RELEVANT} Sample {index}.") for index in range(4, 7)]
    outcome = await rerank_candidates(resources, query=QUERY, nodes=nodes, reranker=LOCAL)
    assert (outcome.nodes, outcome.reranked, outcome.reranker) == (nodes, False, LOCAL)
    assert outcome.skipped == "RERANKER_TIMEOUT" and outcome.scores == {}
    assert len(requests) < len(nodes) and outcome.elapsed_ms < 1200
    async with resources.sessions() as session:
        assert (await session.scalars(select(ModelUse))).all() == []  # the slot was released


@pytest.fixture
async def client(resources):
    from app.main import create_app

    app = create_app(resources.settings)
    app.state.resources = resources
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def rerankers(client):
    response = await client.get("/api/v1/retrieval/profiles")
    assert response.status_code == 200, response.text
    return {item["key"]: item for item in response.json()["rerankers"]}


async def test_given_no_providers_when_listing_profiles_then_rerankers_say_how_to_enable_them(
    resources, client
):
    resources.settings.openai_api_key = None
    items = await rerankers(client)
    assert list(items) == [OPENAI, LOCAL]
    assert items[OPENAI] == {
        "key": OPENAI,
        "provider": "openai",
        "model_id": "gpt-6-luna",
        "display_name": "OpenAI GPT-6 Luna",
        "status": "unavailable",
        "unavailable_reason": "Add an OpenAI API key on the server.",
        "local_model_key": None,
        "candidates": HOSTED.candidates,
    }
    assert items[LOCAL] == {
        "key": LOCAL,
        "provider": "ollama",
        "model_id": "fanyx/Qwen3-Reranker-0.6B-Q8_0",
        "display_name": "Qwen3 Reranker 0.6B (local)",
        "status": "unavailable",
        "unavailable_reason": "Download Qwen3 Reranker 0.6B in Settings.",
        "local_model_key": "qwen3-reranker-0.6b",
        "candidates": ON_DEVICE.candidates,
    }


async def test_given_key_and_verified_install_when_listing_profiles_then_rerankers_are_available(
    resources, client
):
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    await install(resources, local_spec("qwen3-reranker-0.6b"))
    items = await rerankers(client)
    assert [(item["status"], item["unavailable_reason"]) for item in items.values()] == [
        ("available", None),
        ("available", None),
    ]


async def test_given_downloading_reranker_when_listing_profiles_then_its_progress_is_the_reason(
    resources, client
):
    async with resources.sessions() as session, session.begin():
        session.add(ModelInstallation(model_key="qwen3-reranker-0.6b", state="downloading"))
    item = (await rerankers(client))[LOCAL]
    assert item["status"] == "unavailable"
    assert item["unavailable_reason"] == "Wait for the model download to finish."
