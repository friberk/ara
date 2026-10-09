"""Reciprocal rank fusion and token-budgeted evidence packing (ARA-073)."""

from uuid import UUID

from llama_index.core.schema import NodeWithScore, TextNode

from app.integrations.tokens import TiktokenCounter

DOCUMENT = UUID(int=999)
COUNTER = TiktokenCounter()


def node(ordinal: int, *, page: int | None = None, words: int = 20, section="2 Method"):
    return TextNode(
        id_=str(UUID(int=ordinal + 1)),
        text=" ".join(f"word{ordinal}" for _ in range(words)),
        metadata={
            "page": page or ordinal + 1,
            "page_end": page or ordinal + 1,
            "section": section,
            "kind": "text",
            "ordinal": ordinal,
            "document_id": str(DOCUMENT),
        },
    )


def scored(*ordinals: int, **options) -> list[NodeWithScore]:
    return [NodeWithScore(node=node(o, **options), score=1.0) for o in ordinals]


def ids(items) -> list[int]:
    return [UUID(item.node.node_id).int - 1 for item in items]


def cost(passages) -> int:
    return sum(COUNTER.count(passage.render()) for passage in passages)


def test_given_two_rankings_when_fusing_then_shared_nodes_outrank_singletons():
    from app.rag.fusion import reciprocal_rank_fusion

    fused = reciprocal_rank_fusion([scored(1, 2, 3), scored(4, 3, 5)])
    assert ids(fused)[0] == 3
    assert fused[0].score == 1 / 63 + 1 / 62
    assert sorted(ids(fused)) == [1, 2, 3, 4, 5]


def test_given_tied_scores_when_fusing_then_order_is_deterministic_by_ordinal():
    from app.rag.fusion import reciprocal_rank_fusion

    first = reciprocal_rank_fusion([scored(7, 2), scored(4, 9)])
    again = reciprocal_rank_fusion([scored(4, 9), scored(7, 2)])
    assert ids(first) == ids(again) == [4, 7, 2, 9]


def test_given_duplicate_within_one_list_when_fusing_then_its_best_rank_counts_once():
    from app.rag.fusion import reciprocal_rank_fusion

    fused = reciprocal_rank_fusion([scored(1, 2, 1)])
    assert ids(fused) == [1, 2] and fused[0].score == 1 / 61


def test_given_passage_when_rendering_then_handle_section_and_pages_lead():
    from app.rag.packing import Passage

    passage = Passage("S2", UUID(int=1), DOCUMENT, 3, 4, "2 Method", "text", "Body.")
    assert passage.render() == "[S2] 2 Method · p. 3–4\nBody.\n"
    single = Passage("S1", UUID(int=1), DOCUMENT, 3, 3, "", "text", "Body.")
    assert single.render() == "[S1] Untitled section · p. 3\nBody.\n"


def test_given_budget_when_packing_then_rendered_passages_never_exceed_it():
    from app.rag.packing import pack_evidence, render_evidence

    nodes = scored(*range(12), words=60)
    for budget in (0, 50, 90, 200, 333, 1000):
        passages = pack_evidence(nodes, budget=budget, counter=COUNTER)
        assert cost(passages) <= budget
        assert COUNTER.count(render_evidence(passages)) <= budget
    assert len(pack_evidence(nodes, budget=100_000, counter=COUNTER)) == 12


def test_given_ranked_nodes_when_packing_then_handles_follow_document_order():
    from app.rag.packing import pack_evidence

    passages = pack_evidence(scored(5, 1, 3), budget=10_000, counter=COUNTER)
    assert [p.page for p in passages] == [2, 4, 6]
    assert [p.handle for p in passages] == ["S1", "S2", "S3"]
    assert [p.chunk_id for p in passages] == [UUID(int=2), UUID(int=4), UUID(int=6)]
    assert {p.document_id for p in passages} == {DOCUMENT}


def test_given_chunk_boxes_when_packing_then_passages_keep_their_provenance():
    from app.rag.packing import pack_evidence

    hit = node(2)
    hit.metadata["bboxes"] = [[3, 1.0, 2.0, 3.0, 4.0]]
    (passage,) = pack_evidence([NodeWithScore(node=hit)], budget=10_000, counter=COUNTER)
    assert (passage.ordinal, passage.kind, passage.section) == (2, "text", "2 Method")
    assert passage.bboxes == [[3, 1.0, 2.0, 3.0, 4.0]]


def test_given_tight_budget_when_packing_then_relevance_decides_what_fits():
    from app.rag.packing import pack_evidence

    one = pack_evidence(scored(5), budget=10_000, counter=COUNTER)
    passages = pack_evidence(scored(5, 1, 3), budget=cost(one) + 5, counter=COUNTER)
    assert [p.page for p in passages] == [6]


def test_given_oversized_node_when_packing_then_it_is_skipped_not_truncated():
    from app.rag.packing import pack_evidence

    nodes = [*scored(0, words=2000), *scored(1, 2)]
    passages = pack_evidence(nodes, budget=300, counter=COUNTER)
    assert [p.page for p in passages] == [2, 3]
    assert all(p.text == node(p.page - 1).text for p in passages)


def test_given_spare_budget_when_packing_then_same_section_neighbours_are_added():
    from app.rag.packing import pack_evidence

    hit = scored(4)
    neighbours = {hit[0].node.node_id: [node(3), node(5)]}
    roomy = pack_evidence(hit, budget=10_000, counter=COUNTER, neighbours=neighbours)
    assert [p.page for p in roomy] == [4, 5, 6]
    assert [p.handle for p in roomy] == ["S1", "S2", "S3"]
    alone = pack_evidence(hit, budget=10_000, counter=COUNTER)
    tight = pack_evidence(hit, budget=cost(alone) + 5, counter=COUNTER, neighbours=neighbours)
    assert [p.page for p in tight] == [5]


def test_given_neighbour_already_ranked_when_packing_then_it_appears_once():
    from app.rag.packing import pack_evidence

    hits = scored(4, 5)
    neighbours = {hits[0].node.node_id: [node(5)], hits[1].node.node_id: [node(4)]}
    passages = pack_evidence(hits, budget=10_000, counter=COUNTER, neighbours=neighbours)
    assert [p.page for p in passages] == [5, 6]


def test_given_many_nodes_when_packing_then_passages_are_capped():
    from app.rag.packing import pack_evidence

    neighbours = {str(UUID(int=1)): [node(40)]}
    passages = pack_evidence(
        scored(*range(30), words=5),
        budget=100_000,
        counter=COUNTER,
        neighbours=neighbours,
        max_passages=16,
    )
    assert len(passages) == 16 and passages[-1].handle == "S16"
    assert [p.page for p in passages] == list(range(1, 17))
