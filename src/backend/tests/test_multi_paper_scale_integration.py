"""Chats over any number of papers (ARA-088): thirty papers stay bounded in queries and budget.

The user removed the paper cap on 2026-10-10. Search is one filtered query across the chat's
documents, so the statements an answer runs do not grow with the number of papers, and routing
keeps the papers the question names and then the most relevant ones.
"""

import json
import re
from contextlib import contextmanager
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import event

from app.integrations.tokens import PromptMessage, count_messages
from tests.support.answers import ask, named, use_hosted
from tests.support.chats import new_chat
from tests.support.evidence import CHUNK_SET, OPENAI, TITLE, seed_structured
from tests.support.models import hosted_responses
from tests.support.providers import openai_fixture

pytestmark = pytest.mark.integration

MODEL, EFFORT = "gpt-5.6-luna", "low"
NAMED = "Graph Coloring Heuristics"
FOLDING = [
    (
        "1 Protein folding",
        "text",
        1,
        1,
        "Protein folding structures are predicted from amino acid sequences with attention.",
    ),
    (
        "2 Methods",
        "text",
        2,
        2,
        "Structures are refined by molecular dynamics with a learned force field and sampling.",
    ),
    (
        "3 Results",
        "text",
        3,
        3,
        "The refined structures lower the backbone deviation on the benchmark proteins.",
    ),
]
QUESTION = f"What recall does BM25 reach, and what does {NAMED} report?"
GROUP = re.compile(r"^Paper (\d+): (.*)$", re.M)
HANDLE = re.compile(r"^\[(S\d+)\] ", re.M)


@pytest.fixture
def embeddings(resources, monkeypatch):
    from app.integrations import embeddings
    from app.rag import pipeline

    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    monkeypatch.setattr(
        pipeline,
        "create_embedder",
        lambda resources, profile: embeddings.create_embedder(
            resources, profile, transport=openai_fixture([])
        ),
    )


async def library(resources, count: int) -> list[tuple]:
    """`count` papers in chat order: folding studies, then the named paper, then the one whose
    text answers the question, so neither order nor position decides what is kept."""
    seeded = [
        await seed_structured(resources, title=f"Folding study {n}", sections=FOLDING)
        for n in range(count - 2)
    ]
    seeded.append(await seed_structured(resources, title=NAMED, sections=FOLDING))
    seeded.append(await seed_structured(resources))
    return seeded


@contextmanager
def statements(resources):
    """Counts the SQL statements run inside the block."""
    seen = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    engine = resources.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def groups(prompt: str) -> dict[str, int]:
    """Passages under each "Paper N: label" header, by label."""
    found, current = {}, None
    for line in prompt.splitlines():
        if header := GROUP.match(line):
            current = header[2]
            found[current] = 0
        elif HANDLE.match(line) and current is not None:
            found[current] += 1
    return found


def sent(counter, body: dict) -> int:
    messages = [PromptMessage("system", body["instructions"])] + [
        PromptMessage(item["role"], item["content"]) for item in body["input"]
    ]
    return count_messages(counter, messages)


async def test_given_three_or_thirty_papers_when_retrieving_then_the_same_statements_run(
    resources, embeddings
):
    """Search cost does not depend on N: one filtered query per list, one pool, one rerank."""
    from app.integrations.tokens import TiktokenCounter
    from app.rag.pipeline import Scope, retrieve_evidence

    seeded = await library(resources, 30)
    scopes = [
        Scope(document, CHUNK_SET, f"Paper {n}: x") for n, (_, document, _) in enumerate(seeded, 1)
    ]
    counts = []
    for chosen in (scopes[-3:], scopes):
        with statements(resources) as seen:
            result = await retrieve_evidence(
                resources,
                scopes=chosen,
                preferred_profile=OPENAI,
                queries=["BM25 recall", "dense retrieval"],
                question=QUESTION,
                budget=20_000,
                counter=TiktokenCounter(),
                sub_questions=[(len(chosen) - 1, "What recall does BM25 reach?")],
            )
        counts.append(len(seen))
        # Two queries and one sub-question, each a keyword and a vector list of at most 30.
        assert result.passages and result.summary.passages_found <= 30 * 6
    assert counts[0] == counts[1]


async def test_given_three_or_thirty_papers_when_admitting_a_question_then_the_same_statements_run(
    resources,
):
    from app.schemas.ai import ChatInput
    from app.services import chat

    seeded = await library(resources, 30)
    resources.settings.openai_api_key = SecretStr("http-fixture-only")
    counts = []
    for chosen in (seeded[-3:], seeded):
        chat_id = await new_chat(resources, *[(paper, document) for paper, document, _ in chosen])
        body = ChatInput(content=QUESTION, request_id=uuid4(), model=MODEL, reasoning_effort=EFFORT)
        with statements(resources) as seen:
            await chat.prepare(resources, chat_id, body)
        counts.append(len(seen))
    assert counts[0] == counts[1]


async def test_given_thirty_papers_when_asking_then_named_and_relevant_papers_answer_within_budget(
    resources, monkeypatch, embeddings
):
    from app.integrations.context_registry import context_profile
    from app.rag.selection import FIRST_PASS, FLOOR

    seeded = await library(resources, 30)
    chat_id = await new_chat(resources, *[(paper, document) for paper, document, _ in seeded])
    plan = {
        "standalone_question": QUESTION,
        "search_queries": ["BM25 recall"],
        "needs_paper_evidence": True,
        "sub_questions": [],
    }
    planner = hosted_responses(monkeypatch, resources, lambda body: json.dumps(plan))
    calls = []

    def cite_all(body):
        return "Reported " + "".join(f"[{h}]" for h in HANDLE.findall(body["input"][-1]["content"]))

    use_hosted(monkeypatch, resources, calls, cite_all)
    _, events = await ask(resources, chat_id, QUESTION, model=MODEL, reasoning_effort=EFFORT)
    (completed,) = named(events, "message.completed")
    profile = context_profile(resources, MODEL, EFFORT)

    (planned,) = planner
    (answer,) = calls
    for body in (planned, answer):
        assert sent(profile.counter, body) <= profile.input_budget
    # The planner sees a bounded list with the named paper first.
    listed = re.findall(r"^Paper (\d+): (.*)$", planned["instructions"], re.M)
    assert len(listed) <= 20 and listed[0] == ("29", f"{NAMED} (Ada Researcher et al., 2024)")
    # The system prompt does not list thirty papers; evidence headers name the answering ones.
    assert "Folding study" not in answer["instructions"]
    evidence = groups(answer["input"][-1]["content"])
    labels = list(evidence)
    assert any(label.startswith(NAMED) for label in labels)
    assert any(label.startswith(TITLE) for label in labels)
    # At most 24 / 2 = 12 papers keep their floor in the first pass (ARA-094).
    assert len(labels) <= FIRST_PASS.answering_papers == 12
    assert all(count >= FLOOR for count in evidence.values())
    assert "most relevant papers" in completed["retrieval"]["note"]
    assert completed["context"]["input_tokens"] <= profile.input_budget
