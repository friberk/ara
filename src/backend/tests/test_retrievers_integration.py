"""Paper-scoped keyword and vector retrievers over the real PostgreSQL (ARA-073, ARA-088)."""

from uuid import uuid4

import pytest
from llama_index.core.schema import QueryBundle

from app.models.research import DocumentChunk
from tests.support.evidence import CHUNK_SET, OPENAI, embedding_rows, seed_structured
from tests.support.vectors import fixture_vector

pytestmark = pytest.mark.integration

OTHER = [
    (
        "1 Protein folding",
        "text",
        1,
        1,
        "Protein folding structures are predicted from amino acid sequences with attention.",
    )
]


def lexical(resources, *document_ids, **options):
    from app.rag.retrievers import PgLexicalRetriever

    scopes = [(document_id, CHUNK_SET) for document_id in document_ids]
    return PgLexicalRetriever(resources.sessions, scopes, **options)


def vector(resources, *document_ids, **options):
    from app.rag.retrievers import PgVectorRetriever

    scopes = [(document_id, CHUNK_SET) for document_id in document_ids]
    return PgVectorRetriever(resources.sessions, scopes, OPENAI, **options)


def query(text: str) -> QueryBundle:
    return QueryBundle(query_str=text, embedding=fixture_vector(text, 3072))


async def test_given_keyword_question_when_retrieving_then_results_table_ranks_first(resources):
    _, document_id, chunk_ids = await seed_structured(resources)
    found = await lexical(resources, document_id).aretrieve("BM25 recall")
    assert found and found[0].node.node_id == str(chunk_ids[3])
    assert found[0].node.metadata == {
        "page": 3,
        "page_end": 3,
        "section": "3 Results",
        "kind": "table",
        "ordinal": 3,
        "document_id": str(document_id),
        "bboxes": [[3, 72.0, 90.0, 540.0, 180.0]],
    }
    assert found[0].score > 0


async def test_given_no_keyword_matches_all_words_when_retrieving_then_any_word_matches(
    resources,
):
    _, document_id, chunk_ids = await seed_structured(resources)
    found = await lexical(resources, document_id).aretrieve("Okapi weighting for transformers?")
    assert [item.node.node_id for item in found] == [str(chunk_ids[2])]


async def test_given_paraphrase_when_searching_vectors_then_method_is_in_top_three(resources):
    _, document_id, chunk_ids = await seed_structured(resources)
    found = await vector(resources, document_id).aretrieve(
        query("Which weighting and vocabulary does the index use?")
    )
    assert str(chunk_ids[2]) in [item.node.node_id for item in found[:3]]
    assert all(-1 <= item.score <= 1 for item in found)
    assert [item.score for item in found] == sorted((item.score for item in found), reverse=True)


async def test_given_two_papers_when_retrieving_then_only_the_chat_document_answers(resources):
    _, document_id, chunk_ids = await seed_structured(resources)
    _, other_id, other_chunks = await seed_structured(resources, sections=OTHER)
    # An older chunk set of the same document is never searched either.
    async with resources.sessions() as session, session.begin():
        stale = DocumentChunk(
            id=uuid4(),
            document_id=document_id,
            chunk_set="layout-v0:old",
            ordinal=0,
            heading="Protein folding",
            page=1,
            page_end=1,
            text="Protein folding with attention.",
            context_text="Protein folding with attention.",
            token_count=5,
        )
        session.add(stale)
        await session.flush()
        session.add_all(embedding_rows(document_id, [stale], OPENAI))
    assert await lexical(resources, document_id).aretrieve("protein folding") == []
    found = await vector(resources, document_id).aretrieve(query("protein folding"))
    assert {item.node.node_id for item in found} <= {str(chunk_id) for chunk_id in chunk_ids}
    assert {item.node.metadata["document_id"] for item in found} == {str(document_id)}
    other = await vector(resources, other_id).aretrieve(query("protein folding"))
    assert [item.node.node_id for item in other] == [str(other_chunks[0])]


async def test_given_references_when_retrieving_by_default_then_they_are_excluded(resources):
    _, document_id, chunk_ids = await seed_structured(resources)
    references = str(chunk_ids[4])
    question = "Robertson Zaragoza probabilistic relevance framework"
    assert await lexical(resources, document_id).aretrieve(question) == []
    found = await vector(resources, document_id).aretrieve(query(question))
    assert references not in {item.node.node_id for item in found}
    included = await lexical(resources, document_id, include_references=True).aretrieve(question)
    assert [item.node.node_id for item in included] == [references]
    found = await vector(resources, document_id, include_references=True).aretrieve(query(question))
    assert found[0].node.node_id == references


async def test_given_staged_rebuild_vectors_when_searching_then_only_serving_vectors_count(
    resources,
):
    _, document_id, chunk_ids = await seed_structured(resources)
    async with resources.sessions() as session, session.begin():
        chunks = [await session.get(DocumentChunk, chunk_id) for chunk_id in chunk_ids]
        session.add_all(embedding_rows(document_id, chunks, OPENAI + "#r"))
    found = await vector(resources, document_id).aretrieve(query("dense retrieval recall"))
    ids = [item.node.node_id for item in found]
    assert len(ids) == len(set(ids)) == 4


async def test_given_top_k_when_retrieving_then_results_are_capped(resources):
    _, document_id, _ = await seed_structured(resources)
    assert len(await lexical(resources, document_id, top_k=1).aretrieve("BM25")) == 1
    assert len(await vector(resources, document_id, top_k=2).aretrieve(query("BM25"))) == 2


async def test_given_query_without_embedding_when_searching_vectors_then_it_is_rejected(
    resources,
):
    _, document_id, _ = await seed_structured(resources)
    with pytest.raises(ValueError, match="embedding"):
        await vector(resources, document_id).aretrieve("BM25 recall")


async def test_given_two_papers_in_scope_when_searching_vectors_then_each_keeps_its_top_k(
    resources,
):
    """One filtered vector search spans the chat's papers; each paper keeps its share of top k."""
    _, first, first_chunks = await seed_structured(resources)
    _, second, second_chunks = await seed_structured(resources, sections=OTHER)
    found = await vector(resources, first, second, top_k=4).aretrieve(query("protein folding"))
    by_paper = [item.node.metadata["document_id"] for item in found]
    assert by_paper.count(str(first)) == 2 and by_paper.count(str(second)) == 1
    assert found[0].node.node_id == str(second_chunks[0])
    assert [item.score for item in found] == sorted((item.score for item in found), reverse=True)
    assert {item.node.node_id for item in found} <= {
        str(chunk_id) for chunk_id in [*first_chunks, *second_chunks]
    }


async def test_given_one_paper_has_every_word_when_searching_keywords_then_another_may_match_any(
    resources,
):
    """The any-word fallback runs per paper, after the papers that match every word."""
    _, first, first_chunks = await seed_structured(resources)
    folding = [("1 Folding", "text", 1, 1, "Folding models recall motifs from sequences.")]
    _, second, second_chunks = await seed_structured(resources, sections=folding)
    found = await lexical(resources, first, second).aretrieve("recall latency")
    assert [item.node.node_id for item in found] == [str(first_chunks[3]), str(second_chunks[0])]


async def test_given_many_papers_in_scope_when_searching_then_the_list_stays_within_top_k(
    resources,
):
    """However many papers a chat has, one search returns at most top k passages, and no paper
    takes more than max(2, ceil(top k / N)) of them, so several papers reach the pool."""
    from collections import Counter

    documents = [(await seed_structured(resources, title=f"Paper {n}"))[1] for n in range(3)]
    for retriever, ask in (
        (vector(resources, *documents, top_k=4), query("dense retrieval recall")),
        (lexical(resources, *documents, top_k=4), "retrieval"),
    ):
        found = await retriever.aretrieve(ask)
        per_paper = Counter(item.node.metadata["document_id"] for item in found)
        assert len(found) == 4 and max(per_paper.values()) <= 2 and len(per_paper) >= 2
