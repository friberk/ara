"""Papers a question mentions with composer pills (ARA-096): request shape and routing."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.services.context import PaperHeader

LABEL = "Karpukhin 2020"


def body(content: str, *mentions: dict):
    from app.schemas.ai import ChatInput

    return ChatInput(content=content, request_id=uuid4(), mentions=list(mentions))


def mention(start: int, label: str = LABEL, paper_id=None) -> dict:
    return {
        "paper_id": str(paper_id or uuid4()),
        "label": label,
        "start": start,
        "end": start + len(label),
    }


def test_given_pills_when_a_question_is_sent_then_spans_index_its_text_in_code_points():
    # The emoji is one code point in Python and two UTF-16 units in the browser.
    content = f"🔬 How does {LABEL} differ from Khattab 2020?"
    sent = body(content, mention(11), mention(38, "Khattab 2020"))
    assert [content[item.start : item.end] for item in sent.mentions] == [LABEL, "Khattab 2020"]
    assert body("No pills here").mentions == []


def test_given_a_title_as_the_pill_label_then_its_span_matches_with_punctuation_and_accents():
    """Pills carry the paper title (ARA-096 follow-up); the server checks it like any label."""
    title = "Dense Passage Retrieval: Open-Domain QA — Zürich (v2)"
    content = f"Compare {title} with BM25."
    sent = body(content, mention(8, title))
    assert content[sent.mentions[0].start : sent.mentions[0].end] == title


@pytest.mark.parametrize(
    "mentions",
    [
        [mention(0)],  # The span holds other text.
        [mention(45)],  # Past the end of the question.
        [mention(9), mention(9)],  # Overlapping pills.
        [mention(36, "Khattab 2020"), mention(9)],  # Out of order.
        [{**mention(9), "label": " "}],  # A blank label.
    ],
)
def test_given_spans_that_do_not_match_the_text_then_the_question_is_refused(mentions):
    with pytest.raises(ValidationError):
        body(f"How does {LABEL} differ from Khattab 2020?", *mentions)


def prepared(question: str, mentioned: list[int]):
    from app.models.research import ChatMessage
    from app.services.chat import Prepared

    papers = [
        PaperHeader("Dense Passage Retrieval", ["Vladimir Karpukhin"], 2020),
        PaperHeader("ColBERT", ["Omar Khattab"], 2020),
        PaperHeader("Go", ["Ada Researcher"], None),
    ]
    return Prepared(
        ChatMessage(id=uuid4()), replay=False, question=question, papers=papers, mentioned=mentioned
    )


def test_given_a_mentioned_paper_when_evidence_is_allocated_then_it_is_kept_by_its_id():
    """The pill names the paper even when its label alone would not ("Go" is too short)."""
    from app.services.chat import kept_papers, named_in
    from app.services.memory import QueryPlan

    asked = prepared("What does Go report?", mentioned=[2])
    plan = QueryPlan(asked.question, [asked.question], needs_paper_evidence=True, source="model")
    assert named_in(asked, asked.question) == [2]
    assert kept_papers(asked, plan) == [2]
    # Typed names still count alongside pills.
    both = prepared("Compare Karpukhin 2020 with Go.", mentioned=[2])
    assert kept_papers(both, plan) == [0, 2]
