"""Evidence from several papers: per-paper floors, relevance routing and grouping (ARA-088)."""

from uuid import UUID

from llama_index.core.schema import NodeWithScore, TextNode

from app.integrations.tokens import TiktokenCounter

COUNTER = TiktokenCounter()
PAPERS = {name: UUID(int=900 + index) for index, name in enumerate("ABCDE")}
HEADERS = {
    str(PAPERS[name]): f'Paper {n}: Author {name} 2024, "Title {name}"'
    for n, name in enumerate("ABCDE", start=1)
}


def hit(paper: str, ordinal: int, *, words: int = 40) -> NodeWithScore:
    """A ranked passage of `paper`; ids are unique across papers."""
    node = TextNode(
        id_=str(UUID(int=(ord(paper) << 16) + ordinal + 1)),
        text=" ".join(f"{paper.lower()}{ordinal}" for _ in range(words)),
        metadata={
            "page": ordinal + 1,
            "page_end": ordinal + 1,
            "section": "Results",
            "kind": "text",
            "ordinal": ordinal,
            "document_id": str(PAPERS[paper]),
        },
    )
    return NodeWithScore(node=node, score=1.0)


def papers_of(passages) -> list[str]:
    names = {value: key for key, value in PAPERS.items()}
    return [names[passage.document_id] for passage in passages]


def size(item: NodeWithScore, max_passages: int = 16) -> int:
    from app.rag.packing import SEPARATOR, node_passage

    passage = node_passage(item.node, f"S{max_passages}")
    return COUNTER.count(passage.render()) + COUNTER.count(SEPARATOR)


def header_size(name: str) -> int:
    from app.rag.packing import SEPARATOR

    return COUNTER.count(HEADERS[str(PAPERS[name])] + "\n") + COUNTER.count(SEPARATOR)


def test_given_one_dominant_paper_when_packing_then_every_paper_gets_its_floor_first():
    from app.rag.packing import pack_evidence

    ranked = [*(hit("A", n) for n in range(10)), hit("B", 0), hit("B", 1), hit("C", 0), hit("C", 1)]
    passages = pack_evidence(
        ranked, budget=100_000, counter=COUNTER, max_passages=8, headers=HEADERS
    )
    chosen = papers_of(passages)
    assert len(passages) == 8
    assert chosen.count("B") == 2 and chosen.count("C") == 2 and chosen.count("A") == 4
    # Relevance shares the rest: A's best passages, not its later ones.
    assert {p.page for p in passages if p.document_id == PAPERS["A"]} == {1, 2, 3, 4}


def test_given_room_for_two_floors_when_packing_then_the_two_most_relevant_papers_answer():
    from app.rag.packing import pack_evidence

    # Relevance order: C, then A, then B; every paper has three candidates of equal size.
    ranked = [hit("C", 0), hit("A", 0), hit("B", 0), hit("C", 1), hit("A", 1), hit("B", 1)]
    ranked += [hit("C", 2), hit("A", 2), hit("B", 2)]
    floor = header_size("A") + 2 * size(ranked[0])
    passages = pack_evidence(ranked, budget=2 * floor + 10, counter=COUNTER, headers=HEADERS)
    assert sorted(set(papers_of(passages))) == ["A", "C"]
    assert papers_of(passages).count("A") == papers_of(passages).count("C") == 2


def test_given_room_for_less_than_one_floor_when_packing_then_the_best_paper_still_answers():
    from app.rag.packing import pack_evidence

    ranked = [hit("B", 0), hit("A", 0), hit("B", 1), hit("A", 1)]
    budget = header_size("B") + size(ranked[0]) + 5
    passages = pack_evidence(ranked, budget=budget, counter=COUNTER, headers=HEADERS)
    assert papers_of(passages) == ["B"]


def test_given_several_papers_when_rendering_then_groups_follow_chat_order_within_budget():
    from app.rag.packing import pack_evidence, render_evidence

    ranked = [hit("C", 5), hit("A", 3), hit("C", 1), hit("A", 0), hit("B", 2), hit("B", 7)]
    passages = pack_evidence(ranked, budget=100_000, counter=COUNTER, headers=HEADERS)
    assert papers_of(passages) == ["A", "A", "B", "B", "C", "C"]
    assert [p.page for p in passages] == [1, 4, 3, 8, 2, 6]
    assert [p.handle for p in passages] == [f"S{n}" for n in range(1, 7)]
    rendered = render_evidence(passages, HEADERS)
    first, second, third = (HEADERS[str(PAPERS[name])] for name in "ABC")
    assert rendered.index(first) < rendered.index("[S1]") < rendered.index(second)
    assert rendered.index(second) < rendered.index("[S3]") < rendered.index(third)
    for budget in (0, 120, 300, 700, 1500):
        packed = pack_evidence(ranked, budget=budget, counter=COUNTER, headers=HEADERS)
        assert COUNTER.count(render_evidence(packed, HEADERS)) <= budget


def test_given_five_papers_and_a_tight_budget_when_packing_then_floors_hold_or_papers_route():
    from app.rag.packing import pack_evidence

    ranked = [hit(name, n, words=60) for n in range(6) for name in "EDCBA"]
    for budget in range(400, 6000, 137):
        passages = pack_evidence(ranked, budget=budget, counter=COUNTER, headers=HEADERS)
        counts = {name: papers_of(passages).count(name) for name in "ABCDE"}
        answering = [name for name in "EDCBA" if counts[name]]
        # Every answering paper has its floor, and the answering papers are the most relevant.
        assert all(counts[name] >= 2 for name in answering) or len(answering) == 1
        assert answering == list("EDCBA")[: len(answering)]
