"""Papers a question names are always kept in a multi-paper answer (ARA-088)."""

from app.services.context import PaperHeader

PAPERS = [
    PaperHeader(
        "Dense Passage Retrieval for Open-Domain QA", ["Vladimir Karpukhin", "Barlas Oguz"], 2020
    ),
    PaperHeader("ColBERT", ["Omar Khattab"], 2020),
    PaperHeader("Go", ["Ada Researcher"], None),
    PaperHeader("Attention Is All You Need", ["Vaswani, Ashish"], 2017),
]


def named(question: str) -> list[int]:
    from app.services.chat_papers import named_papers

    return named_papers(question, PAPERS)


def test_given_a_title_or_a_chip_name_when_asking_then_that_paper_is_named():
    assert named("How does dense passage retrieval for open-domain QA train?") == [0]
    assert named("Compare Karpukhin 2020 with Vaswani 2017.") == [0, 3]


def test_given_an_at_mention_from_the_composer_when_asking_then_that_paper_is_named():
    assert named("How does @Khattab 2020 differ from @Karpukhin 2020?") == [0, 1]
    assert named("@ColBERT: what is late interaction?") == [1]


def test_given_words_that_only_resemble_a_name_then_no_paper_is_named():
    # "Go" is too short to name a paper; a surname without its year is not a chip name.
    assert named("Should we go with Karpukhin's approach, or Khattab's?") == []
    assert named("What does colbertization mean?") == []
