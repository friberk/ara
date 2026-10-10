"""Relevance-driven evidence end to end: section expansion by question type (ARA-094)."""

import pytest

from tests.support.evidence import CHUNK_SET, seed_structured

pytestmark = pytest.mark.integration

FILLER = "The procedure paragraph {n} describes preprocessing and tokenisation steps in detail."
# "2 Method" spans six passages; only the third mentions the Okapi weighting.
METHOD = [
    (
        "2 Method",
        "text",
        2 + n // 3,
        2 + n // 3,
        "We weight every term with the Okapi formula and a stemmed vocabulary."
        if n == 2
        else FILLER.format(n=n),
    )
    for n in range(6)
]
SECTIONS = [
    ("1 Introduction", "text", 1, 1, "Researchers ask precise questions about baselines."),
    *METHOD,
    ("3 Results", "text", 4, 4, "Dense retrieval improves recall over the lexical index."),
]


async def keyword_evidence(resources, document_id, *, question_type: str):
    from app.integrations.tokens import TiktokenCounter
    from app.rag.pipeline import Scope, retrieve_evidence

    return await retrieve_evidence(
        resources,
        scopes=[Scope(document_id, CHUNK_SET)],
        preferred_profile="openai-3-large",
        queries=["Okapi weighting"],
        question="How are terms weighted?",
        budget=50_000,
        counter=TiktokenCounter(),
        question_type=question_type,
    )


async def test_given_a_broad_question_when_packing_then_selected_chunks_grow_to_their_section(
    resources,
):
    _, document_id, chunk_ids = await seed_structured(resources, sections=SECTIONS, profile=None)
    method = {str(chunk_id) for chunk_id in chunk_ids[1:7]}

    broad = await keyword_evidence(resources, document_id, question_type="broad")
    assert {str(item.chunk_id) for item in broad.passages} == method
    assert broad.summary.question_type == "broad"

    lookup = await keyword_evidence(resources, document_id, question_type="lookup")
    # A lookup keeps the conservative first pass: the match and its two neighbours.
    assert {str(item.chunk_id) for item in lookup.passages} == {
        str(chunk_id) for chunk_id in chunk_ids[2:5]
    }


async def test_given_the_planner_calls_a_follow_up_broad_when_answering_then_its_section_is_sent(
    resources, monkeypatch
):
    import json

    from tests.support.answers import ask, named, use_hosted
    from tests.support.chats import add_turns, new_chat
    from tests.support.models import hosted_responses

    paper_id, document_id, chunk_ids = await seed_structured(
        resources, sections=SECTIONS, profile=None
    )
    chat_id = await new_chat(resources, (paper_id, document_id))
    await add_turns(resources, chat_id, [("What is the paper about?", "Retrieval.")])
    plan = {
        "standalone_question": "How are terms weighted in the method?",
        "search_queries": ["Okapi weighting"],
        "needs_paper_evidence": True,
        "sub_questions": [],
        "question_type": "broad",
    }
    hosted_responses(monkeypatch, resources, lambda body: json.dumps(plan))
    calls = []
    use_hosted(monkeypatch, resources, calls, lambda body: "Terms use Okapi [S1].")
    _, events = await ask(resources, chat_id, "And how is it weighted?")
    (completed,) = named(events, "message.completed")
    assert completed["retrieval"]["question_type"] == "broad"
    prompt = calls[0]["input"][-1]["content"]
    assert all(f"paragraph {n} describes" in prompt for n in (0, 1, 3, 4, 5))
