"""Relevance-driven evidence: pruning, first-pass caps and floors at the new cap (ARA-094).

Scores are synthetic reranker probabilities; the distributions mirror the shapes the Decisions
reranker produces (often 1.0 at the top, then a long tail).
"""

from uuid import UUID

from llama_index.core.schema import NodeWithScore, TextNode

from app.integrations.tokens import TiktokenCounter

COUNTER = TiktokenCounter()
DOCUMENT = UUID(int=7000)
PAPERS = {name: UUID(int=7100 + index) for index, name in enumerate("ABCDEFGHIJKLMNOP")}


def candidate(ordinal: int, *, paper: str | None = None, words: int = 20) -> NodeWithScore:
    document = PAPERS[paper] if paper else DOCUMENT
    node = TextNode(
        id_=str(UUID(int=(document.int << 12) + ordinal + 1)),
        text=" ".join(f"w{ordinal}" for _ in range(words)),
        metadata={
            "page": ordinal + 1,
            "page_end": ordinal + 1,
            "section": "Results",
            "kind": "text",
            "ordinal": ordinal,
            "document_id": str(document),
        },
    )
    return NodeWithScore(node=node, score=0.0)


def ranked_with(scores: list[float | None], **options):
    """Candidates in reranked order and the reranker's scores (None: not scored)."""
    nodes = [candidate(index, **options) for index in range(len(scores))]
    found = {item.node.node_id: score for item, score in zip(nodes, scores, strict=True) if score}
    return nodes, found


def evidence(nodes, scores, **fields):
    from app.rag.pipeline import EvidenceResult
    from app.schemas.ai import RetrievalSummary

    return EvidenceResult(
        [],
        RetrievalSummary(mode="hybrid"),
        {},
        list(nodes),
        counter=COUNTER,
        scores=scores,
        **fields,
    )


def test_given_a_steep_score_tail_when_pruning_then_passages_far_below_the_top_are_dropped():
    from app.rag.selection import PRUNE_RATIO, prune

    nodes, scores = ranked_with([0.98, 0.95, 0.6, 0.45, 0.2, 0.05])
    result = prune(nodes, scores, ratio=PRUNE_RATIO)
    assert [item.node.node_id for item in result.kept] == [n.node.node_id for n in nodes[:3]]
    assert result.pruned == 3
    assert result.top == 0.98 and result.bar == 0.98 * PRUNE_RATIO


def test_given_a_flat_distribution_when_pruning_then_nothing_relevant_is_dropped():
    from app.rag.selection import PRUNE_RATIO, prune

    nodes, scores = ranked_with([0.9] * 30)
    result = prune(nodes, scores, ratio=PRUNE_RATIO)
    assert len(result.kept) == 30 and result.pruned == 0


def test_given_one_strong_passage_when_pruning_then_the_floor_is_kept_and_nothing_padded():
    from app.rag.selection import PRUNE_RATIO, prune

    nodes, scores = ranked_with([0.99, 0.1, 0.08, 0.05, 0.01])
    result = prune(nodes, scores, ratio=PRUNE_RATIO)
    # At least the per-paper floor of two passages answers, never more than that below the bar.
    assert [item.node.node_id for item in result.kept] == [n.node.node_id for n in nodes[:2]]
    assert result.pruned == 3


def test_given_unscored_candidates_when_pruning_then_only_judged_passages_survive():
    from app.rag.selection import PRUNE_RATIO, prune

    # The reranker scores only its head; the tail and failed calls carry no score.
    nodes, scores = ranked_with([0.9, 0.8, None, 0.7, None, None])
    result = prune(nodes, scores, ratio=PRUNE_RATIO)
    assert [item.node.node_id for item in result.kept] == [
        nodes[0].node.node_id,
        nodes[1].node.node_id,
        nodes[3].node.node_id,
    ]
    assert result.pruned == 3


def test_given_no_reranker_scores_when_pruning_then_fusion_order_is_kept_whole():
    from app.rag.selection import PRUNE_RATIO, prune

    nodes, _ = ranked_with([None] * 8)
    result = prune(nodes, {}, ratio=PRUNE_RATIO)
    assert result.kept == nodes and result.pruned == 0
    assert result.bar is None and result.top is None


def test_given_a_named_paper_below_the_bar_when_pruning_then_its_floor_survives():
    from app.rag.selection import PRUNE_RATIO, prune

    strong = [candidate(n, paper="A") for n in range(4)]
    weak = [candidate(n, paper="B") for n in range(3)]
    nodes = [*strong, *weak]
    scores = {item.node.node_id: 1.0 for item in strong}
    scores |= {item.node.node_id: 0.05 for item in weak}
    result = prune(nodes, scores, ratio=PRUNE_RATIO, kept={str(PAPERS["B"])})
    kept = [item.node.node_id for item in result.kept]
    assert kept == [item.node.node_id for item in [*strong, *weak[:2]]]
    assert result.pruned == 1


def test_given_the_retry_bar_when_pruning_then_it_keeps_more_than_the_first_pass():
    from app.rag.selection import PRUNE_RATIO, RETRY_PRUNE_RATIO, prune

    nodes, scores = ranked_with([1.0, 0.45, 0.3, 0.2, 0.1])
    first = prune(nodes, scores, ratio=PRUNE_RATIO)
    wider = prune(nodes, scores, ratio=RETRY_PRUNE_RATIO)
    assert len(first.kept) == 2 and len(wider.kept) == 3
    assert RETRY_PRUNE_RATIO < PRUNE_RATIO


def test_given_many_relevant_passages_when_packing_the_first_pass_then_it_stops_at_24():
    from app.rag.selection import FIRST_PASS_PASSAGES

    nodes, scores = ranked_with([0.95] * 40, words=10)
    result = evidence(nodes, scores)
    passages = result.pack(100_000)
    assert FIRST_PASS_PASSAGES == 24
    assert len(passages) == 24
    assert result.summary.passages_used == 24 and result.summary.pruned == 0


def test_given_large_passages_and_a_large_window_when_packing_then_16k_tokens_cap_the_first_pass():
    from app.rag.packing import render_evidence
    from app.rag.selection import FIRST_PASS_TOKENS

    nodes, scores = ranked_with([0.95] * 24, words=1500)
    result = evidence(nodes, scores)
    passages = result.pack(200_000)
    used = COUNTER.count(render_evidence(passages))
    assert FIRST_PASS_TOKENS == 16_000
    assert 0 < used <= FIRST_PASS_TOKENS
    assert result.summary.evidence_tokens == used
    # A smaller evidence ceiling E wins over 16K.
    assert COUNTER.count(render_evidence(result.pack(5_000))) <= 5_000


def test_given_a_pruned_pool_when_packing_then_passages_below_the_bar_never_pad_the_budget():
    nodes, scores = ranked_with([0.97, 0.9, 0.85, 0.2, 0.1, 0.05, 0.02])
    result = evidence(nodes, scores)
    passages = result.pack(100_000)
    assert {str(p.chunk_id) for p in passages} == {n.node.node_id for n in nodes[:3]}
    assert result.summary.pruned == 4
    assert result.trace["prune"]["bar"] == 0.97 * 0.5


def test_given_sixteen_relevant_papers_when_packing_then_twelve_answer_with_their_floor():
    from app.rag.selection import FIRST_PASS_PASSAGES

    names = "ABCDEFGHIJKLMNOP"
    nodes = [candidate(n, paper=name, words=10) for n in range(3) for name in names]
    scores = {item.node.node_id: 0.9 for item in nodes}
    headers = {str(PAPERS[name]): f"Paper {i}: {name}" for i, name in enumerate(names, 1)}
    result = evidence(nodes, scores, headers=headers, documents=list(headers))
    passages = result.pack(100_000)
    counts = {}
    for passage in passages:
        counts[passage.document_id] = counts.get(passage.document_id, 0) + 1
    assert len(counts) == FIRST_PASS_PASSAGES // 2 == 12
    assert all(count == 2 for count in counts.values())
