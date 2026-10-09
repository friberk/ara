"""Second-stage reranking seam (ARA-074). The retrieval pipeline calls only `rerank_candidates`.

`reranker` is a profile key from `app.integrations.reranker_catalog` (None = off). The default
profile scores with the OpenAI Decisions API; the local profile uses Ollama log-probabilities.
Until the rerankers land this is a safe pass-through.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RerankOutcome:
    nodes: list  # the full candidate list, reranked head first; fusion order when skipped
    reranked: bool
    reranker: str | None  # the profile key that ran, or None
    skipped: str | None = None  # plain reason code when reranking did not run
    elapsed_ms: int = 0
    scores: dict[str, float] = field(default_factory=dict)  # node id -> relevance, for the trace


async def rerank_candidates(
    resources, *, query: str, nodes: Sequence, reranker: str | None
) -> RerankOutcome:
    """Reorder fused candidates for `query`. Never raises: failures keep fusion order."""
    return RerankOutcome(
        nodes=list(nodes), reranked=False, reranker=None, skipped="not_implemented"
    )
