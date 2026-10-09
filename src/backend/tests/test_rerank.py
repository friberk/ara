"""Reranking never raises and never calls a provider it cannot use (ARA-074)."""

from types import SimpleNamespace

import httpx

from app.core.config import Settings
from tests.support.nodes import node


def offline(requests, **settings):
    def handler(request):
        requests.append(request)
        return httpx.Response(500)

    return SimpleNamespace(
        settings=Settings(_env_file=None, **settings),
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_given_reranking_off_when_reranking_then_fusion_order_is_kept_without_calls():
    from app.rag.rerank import rerank_candidates

    requests, nodes = [], [node(1, "Method"), node(2, "Results")]
    outcome = await rerank_candidates(
        offline(requests), query="What improves recall?", nodes=nodes, reranker=None
    )
    assert outcome.nodes == nodes and outcome.nodes is not nodes
    assert (outcome.reranked, outcome.reranker, outcome.skipped) == (False, None, None)
    assert outcome.scores == {} and requests == []


async def test_given_unknown_reranker_when_reranking_then_it_is_skipped_plainly():
    from app.rag.rerank import rerank_candidates

    requests, nodes = [], [node(1, "Method")]
    outcome = await rerank_candidates(
        offline(requests), query="What improves recall?", nodes=nodes, reranker="bge-reranker"
    )
    assert (outcome.nodes, outcome.reranked, outcome.reranker) == (nodes, False, None)
    assert outcome.skipped == "INVALID_RERANKER" and requests == []


async def test_given_no_openai_key_when_reranking_then_model_is_not_configured():
    from app.rag.rerank import rerank_candidates

    requests, nodes = [], [node(1, "Method"), node(2, "Recall improves")]
    outcome = await rerank_candidates(
        offline(requests, openai_api_key=""),
        query="What improves recall?",
        nodes=nodes,
        reranker="openai-gpt-6-luna",
    )
    assert (outcome.nodes, outcome.reranked, outcome.reranker) == (
        nodes,
        False,
        "openai-gpt-6-luna",
    )
    assert outcome.skipped == "MODEL_NOT_CONFIGURED" and requests == []


async def test_given_no_candidates_when_reranking_then_nothing_is_called():
    from app.rag.rerank import rerank_candidates

    requests = []
    outcome = await rerank_candidates(
        offline(requests, openai_api_key="sk-fixture"),
        query="What improves recall?",
        nodes=[],
        reranker="openai-gpt-6-luna",
    )
    assert (outcome.nodes, outcome.reranked, outcome.skipped) == ([], False, None)
    assert requests == []


async def test_given_broken_resources_when_reranking_then_the_failure_is_contained():
    from app.rag.rerank import rerank_candidates

    nodes = [node(1, "Method")]
    outcome = await rerank_candidates(
        None, query="What improves recall?", nodes=nodes, reranker="openai-gpt-6-luna"
    )
    assert (outcome.nodes, outcome.reranked, outcome.skipped) == (
        nodes,
        False,
        "RERANKER_FAILED",
    )


def test_given_a_node_when_building_decisions_input_then_it_names_section_and_page():
    from app.rag.rerank import decision_input

    assert decision_input("What improves recall?", node(1, "Recall improves.").node) == (
        "Query:\nWhat improves recall?\n\nPassage (Results · p. 3):\nRecall improves."
    )
    assert decision_input("Q?", node(2, "Text.", section=None, page=7).node) == (
        "Query:\nQ?\n\nPassage (p. 7):\nText."
    )
