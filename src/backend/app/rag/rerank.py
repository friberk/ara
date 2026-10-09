"""Second-stage reranking seam (ARA-074). The retrieval pipeline calls only `rerank_candidates`.

`reranker` is a profile key from `app.integrations.reranker_catalog` (None = off). The default
profile asks the OpenAI Decisions API for a relevance probability per passage; the local profile
reads Qwen3-Reranker's next-token log-probabilities through Ollama. Reranking is optional, so it
never raises: a failure keeps fusion order and records a plain `skipped` code.
"""

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.errors import AppError
from app.integrations.context_registry import HOSTED_ENCODING, LOCAL_ENCODING
from app.integrations.reranker_catalog import (
    RELEVANCE_INSTRUCTIONS,
    RerankerProfile,
    reranker_profile,
)
from app.integrations.tokens import TiktokenCounter, keep_head

logger = logging.getLogger(__name__)

# Phase 0 S4: p50 0.28 s per Decisions call. A slow or failed call simply goes unscored.
DECISIONS_TIMEOUT = 10
# Decisions frames each request beyond our input and instructions; reserve a margin per call.
DECISIONS_FRAMING_TOKENS = 200
# Phase 0 S1: about 0.7 s per local call, plus a 1-3 s reload when the reranker was evicted.
LOCAL_TIMEOUT = 30
LOCAL_KEEP_ALIVE = "10m"
# The raw template takes about 105 tokens of num_ctx 2048; query and document share the rest.
LOCAL_QUERY_TOKENS = 128
LOCAL_DOCUMENT_TOKENS = 1800


@dataclass(frozen=True)
class RerankOutcome:
    nodes: list  # the full candidate list, reranked head first; fusion order when skipped
    reranked: bool
    reranker: str | None  # the profile key that ran, or None
    skipped: str | None = None  # plain reason code when reranking did not run
    elapsed_ms: int = 0
    scores: dict[str, float] = field(default_factory=dict)  # node id -> relevance, for the trace


class Skipped(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def rerank_candidates(
    resources, *, query: str, nodes: Sequence, reranker: str | None
) -> RerankOutcome:
    """Reorder fused candidates for `query`. Never raises: failures keep fusion order.

    Only the first `profile.candidates` nodes are scored; the rest follow unchanged. Off (None)
    is a choice, not a skip. `reranker` names the selected profile even when it was skipped.
    """
    nodes = list(nodes)
    if reranker is None or not nodes:
        return RerankOutcome(nodes=nodes, reranked=False, reranker=None)
    try:
        profile = reranker_profile(reranker)
    except AppError as error:
        return RerankOutcome(nodes=nodes, reranked=False, reranker=None, skipped=error.code)
    started = time.perf_counter()
    head = nodes[: profile.candidates]
    scores, skipped = {}, None
    try:
        if profile.method == "openai-decisions":
            scores = await decisions_scores(resources, profile, query, head)
        else:
            scores = await local_scores(resources, profile, query, head)
    except (Skipped, AppError) as error:
        skipped = error.code
    except Exception as error:
        logger.warning(
            "Reranking failed; fusion order kept",
            extra={"reranker": profile.key, "error_type": type(error).__name__},
        )
    if not scores:
        skipped = skipped or "RERANKER_FAILED"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if skipped:
        return RerankOutcome(
            nodes=nodes,
            reranked=False,
            reranker=profile.key,
            skipped=skipped,
            elapsed_ms=elapsed_ms,
        )
    return RerankOutcome(
        nodes=reordered(nodes, profile.candidates, scores),
        reranked=True,
        reranker=profile.key,
        elapsed_ms=elapsed_ms,
        scores=scores,
    )


def reordered(nodes: list, candidates: int, scores: dict[str, float]) -> list:
    """Scored head by (score desc, fused rank asc), then unscored head, then the untouched tail.
    Decisions often saturates at 1.0, so fused rank is the meaningful tie-break."""
    head = nodes[:candidates]
    ranked = sorted(
        (rank for rank, item in enumerate(head) if item.node.node_id in scores),
        key=lambda rank: (-scores[head[rank].node.node_id], rank),
    )
    unscored = [item for item in head if item.node.node_id not in scores]
    return [head[rank] for rank in ranked] + unscored + nodes[candidates:]


def decision_input(query: str, node) -> str:
    section, page = node.metadata.get("section"), node.metadata.get("page")
    label = " · ".join(filter(None, [section, None if page is None else f"p. {page}"]))
    passage = f"Passage ({label})" if label else "Passage"
    return f"Query:\n{query}\n\n{passage}:\n{node.get_content()}"


def relevance_probability(data) -> float | None:
    """The `relevance` predicate's probability; a refusal or malformed answer has none."""
    answers = data.get("answers") if isinstance(data, dict) else None
    for answer in answers if isinstance(answers, list) else []:
        if isinstance(answer, dict) and answer.get("name") == "relevance":
            probability = answer.get("probability")
            if (
                answer.get("type") == "predicate"
                and type(probability) in {int, float}
                and 0 <= probability <= 1
            ):
                return float(probability)
            return None
    return None


async def decisions_scores(
    resources, profile: RerankerProfile, query: str, head: list
) -> dict[str, float]:
    from openai import APIError, AsyncOpenAI

    from app.integrations.llm import LLMError, configured, reserve_amount

    settings = resources.settings
    if not configured(settings):
        raise Skipped("MODEL_NOT_CONFIGURED")
    inputs = {item.node.node_id: decision_input(query, item.node) for item in head}
    counter = TiktokenCounter(HOSTED_ENCODING)
    framing = counter.count(RELEVANCE_INSTRUCTIONS) + DECISIONS_FRAMING_TOKENS
    tokens = sum(counter.count(text) + framing for text in inputs.values())
    try:
        # Reranking shares the daily ledger under `rerank:<profile>` at its input price.
        await reserve_amount(
            resources,
            f"rerank:{profile.key}",
            profile.price_per_million_input * tokens / Decimal(1_000_000),
        )
    except LLMError as error:
        raise Skipped(error.code) from None
    # The shared process client carries the request; closing this wrapper would close it.
    client = AsyncOpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        base_url=settings.openai_base_url,
        max_retries=0,
        timeout=DECISIONS_TIMEOUT,
        http_client=resources.http,
    )
    slots = asyncio.Semaphore(profile.concurrency)

    async def decide(text: str) -> float | None:
        async with slots:
            try:
                data = await client.post(
                    "/decisions",
                    body={
                        "model": profile.model_id,
                        "input": text,
                        "questions": [
                            {
                                "type": "predicate",
                                "name": "relevance",
                                "instructions": RELEVANCE_INSTRUCTIONS,
                            }
                        ],
                    },
                    cast_to=object,
                )
            except APIError:
                return None
        return relevance_probability(data)

    results = await asyncio.gather(*(decide(text) for text in inputs.values()))
    return {key: score for key, score in zip(inputs, results, strict=True) if score is not None}


async def local_scores(
    resources, profile: RerankerProfile, query: str, head: list
) -> dict[str, float]:
    from app.integrations.model_catalog import local_spec
    from app.services import local_models

    spec = local_spec(profile.local_model_key)
    if spec is None:
        raise Skipped("LOCAL_MODEL_NOT_READY")
    counter = TiktokenCounter(LOCAL_ENCODING, resources.settings.local_token_factor)
    query = keep_head(counter, query, LOCAL_QUERY_TOKENS)
    runtime = local_models.runtime(resources)
    scores = {}
    async with local_models.retrieval_inference_slot(resources, spec.key):
        for item in head:
            document = keep_head(counter, item.node.get_content(), LOCAL_DOCUMENT_TOKENS)
            try:
                score = await runtime.relevance(
                    spec.model_id,
                    query,
                    document,
                    keep_alive=LOCAL_KEEP_ALIVE,
                    timeout_seconds=LOCAL_TIMEOUT,
                )
            except AppError as error:
                if error.code == "LOCAL_RUNTIME_UNAVAILABLE":
                    break  # each further call would wait out its own timeout
                continue
            if score is not None:
                scores[item.node.node_id] = score
    return scores
