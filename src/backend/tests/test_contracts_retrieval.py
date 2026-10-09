"""Frozen retrieval and context contracts shared by backend agents and the UI (ARA-070)."""

from app.main import create_app

PATHS = {
    "/api/v1/retrieval/profiles": {"get"},
    "/api/v1/retrieval/settings": {"get", "put"},
    "/api/v1/papers/{paper_id}/retrieval": {"get", "put"},
    "/api/v1/papers/{paper_id}/retrieval/rebuild": {"post"},
    "/api/v1/chats/{chat_id}/memory": {"get"},
}


def openapi():
    return create_app().openapi()


def test_retrieval_endpoints_are_published():
    paths = openapi()["paths"]
    for path, methods in PATHS.items():
        assert path in paths, path
        assert methods <= set(paths[path]), (path, set(paths[path]))


def test_message_citation_and_model_carry_new_fields():
    schemas = openapi()["components"]["schemas"]
    assert {"retrieval", "context", "grounding"} <= set(schemas["Message"]["properties"])
    citation = schemas["app__schemas__ai__Citation"]["properties"]
    assert {"page_end", "section", "kind", "bboxes"} <= set(citation)
    assert "kind" in schemas["Model"]["properties"]
    summary = schemas["RetrievalSummary"]["properties"]
    assert {
        "mode",
        "profile",
        "reranked",
        "standalone_query",
        "search_queries",
        "passages_found",
        "passages_used",
        "limited_by_context",
        "note",
    } <= set(summary)
    usage = schemas["ContextUsage"]["properties"]
    assert {
        "window",
        "input_tokens",
        "output_reserved",
        "summary_version",
        "recent_turns",
        "recalled_turns",
        "truncated",
    } <= set(usage)


def test_retrieval_dtos_have_exact_shapes():
    schemas = openapi()["components"]["schemas"]
    assert set(schemas["RetrievalSettings"]["properties"]) == {
        "embedding_profile",
        "reranker_enabled",
    }
    assert set(schemas["PaperRetrievalUpdate"]["properties"]) == {"profile", "request_id"}
    assert {
        "effective_profile",
        "source",
        "parser",
        "chunk_count",
        "section_count",
        "mode",
        "mode_note",
        "indexes",
    } <= set(schemas["PaperRetrieval"]["properties"])
    assert {"memory", "total_messages"} == set(schemas["ChatMemoryState"]["properties"])


def test_retrieval_settings_default_to_openai_profile():
    from app.schemas.retrieval import RetrievalSettings

    # ARA-074 is deferred: CPU reranking measured ~54 s per question, so it is off by default.
    assert RetrievalSettings().model_dump() == {
        "embedding_profile": "openai-3-large",
        "reranker_enabled": False,
    }


async def test_indexing_hook_is_a_safe_no_op_until_indexing_lands():
    from app.rag.hooks import after_chunks_persisted

    assert await after_chunks_persisted(None, document_id=None) is None


def test_profiles_page_reports_reranker_availability():
    schemas = openapi()["components"]["schemas"]
    assert "reranker" in schemas["EmbeddingProfilePage"]["properties"]
    assert {
        "model_id",
        "display_name",
        "status",
        "unavailable_reason",
        "local_model_key",
        "candidates",
    } <= set(schemas["RerankerOut"]["properties"])
