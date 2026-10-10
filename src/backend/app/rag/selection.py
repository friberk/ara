"""How much evidence a pass may use and which reranked candidates survive (ARA-094).

docs/plans/retrieval-orchestration.md, steps 4, 5 and 10. These numbers follow published practice
but are not measured on the user's papers; the user decided against a check set.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from llama_index.core.schema import NodeWithScore

# "About 2 passages" per paper before relevance shares the rest: the design's per-paper floor,
# a per-document quota so one long paper cannot crowd out the others (LlamaIndex's
# multi-document pattern; docs/plans/retrieval-orchestration.md, step 7).
FLOOR = 2
# Step 5, the first pass is conservative: OpenAI file search returns up to 20 chunks within a 16K
# token budget for GPT-4-class models, and Anthropic's Contextual Retrieval reranks about 150
# candidates down to 20. The design rounds 20 up to 24 so twelve papers can keep a floor of two.
FIRST_PASS_PASSAGES = 24
FIRST_PASS_TOKENS = 16_000
# Step 4, prune and never pad: retrieved hard negatives degrade long-context generation (Jin et
# al., ICLR 2025), so a passage scoring below half the best one is dropped. With the reranker's
# relevance probability at 1.0 this is the predicate's own decision boundary, 0.5. A design
# choice; not measured.
PRUNE_RATIO = 0.5
# Step 10, the single wider retry (adapting Self-Route, Li et al., EMNLP 2024): half the bar and
# about twice the passages, up to the evidence ceiling E.
RETRY_PRUNE_RATIO = PRUNE_RATIO / 2
RETRY_SCALE = 2


@dataclass(frozen=True)
class EvidencePass:
    """One attempt's evidence limits. `max_tokens` None means up to the evidence ceiling E;
    `reach` is how far selected chunks grow within their section (1: neighbours; None: all)."""

    name: str
    max_passages: int
    max_tokens: int | None
    prune_ratio: float
    reach: int | None

    @property
    def target_tokens(self) -> int:
        """The evidence the pass wants before E bounds it; a retry wants twice the first pass.
        When this exceeds E, a comparison is read paper by paper (step 7)."""
        return self.max_tokens or RETRY_SCALE * FIRST_PASS_TOKENS

    @property
    def answering_papers(self) -> int:
        """Each answering paper needs its floor within the passage cap (step 7)."""
        return self.max_passages // FLOOR


FIRST_PASS = EvidencePass("first", FIRST_PASS_PASSAGES, FIRST_PASS_TOKENS, PRUNE_RATIO, 1)
RETRY_PASS = EvidencePass("retry", RETRY_SCALE * FIRST_PASS_PASSAGES, None, RETRY_PRUNE_RATIO, None)


@dataclass(frozen=True)
class Pruned:
    kept: list[NodeWithScore]
    # Candidates the bar dropped: scored too low, or never scored by the reranker.
    pruned: int
    top: float | None = None
    bar: float | None = None


def prune(
    ranked: Sequence[NodeWithScore],
    scores: Mapping[str, float],
    *,
    ratio: float,
    kept: Collection[str] = (),
) -> Pruned:
    """Candidates scoring at least `ratio` times the best score, in ranked order.

    Without reranker scores nothing is pruned: fusion ranks are not relevance judgements. With
    them, unscored candidates (past the reranker's head, or a failed call) are dropped. Never
    fewer than FLOOR passages survive, and each `kept` paper (named by the question) keeps its
    first FLOOR candidates, so a comparison never loses a paper it asked about.
    """
    ranked = list(ranked)
    judged = [scores[item.node.node_id] for item in ranked if item.node.node_id in scores]
    if not judged:
        return Pruned(ranked, 0)
    top = max(judged)
    bar = top * ratio
    floors: dict[str, int] = {}
    survivors = []
    for index, item in enumerate(ranked):
        document = item.node.metadata.get("document_id")
        score = scores.get(item.node.node_id)
        named = document in kept and floors.get(document, 0) < FLOOR
        if index < FLOOR or named or (score is not None and score >= bar):
            survivors.append(item)
            floors[document] = floors.get(document, 0) + 1
    return Pruned(survivors, len(ranked) - len(survivors), top, bar)
