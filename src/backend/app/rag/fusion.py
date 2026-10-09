"""Reciprocal rank fusion of keyword and vector rankings (ARA-073)."""

from collections.abc import Sequence

from llama_index.core.schema import NodeWithScore

RRF_K = 60


def reciprocal_rank_fusion(
    ranked: Sequence[Sequence[NodeWithScore]], *, k: int = RRF_K
) -> list[NodeWithScore]:
    """Score each node by the sum of 1 / (k + rank) over the lists it appears in.

    A node counts once per list at its best rank. Ties go to the earlier passage in the paper.
    """
    scores: dict[str, float] = {}
    nodes = {}
    for ranking in ranked:
        seen = set()
        for rank, item in enumerate(ranking, start=1):
            key = item.node.node_id
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank)
            nodes.setdefault(key, item.node)
    order = sorted(scores, key=lambda key: (-scores[key], nodes[key].metadata["ordinal"], key))
    return [NodeWithScore(node=nodes[key], score=scores[key]) for key in order]
