"""Frozen retrieval and context contracts shared by backend agents and the UI (ARA-070)."""

from app.main import create_app

PATHS = {
    "/api/v1/retrieval/profiles": {"get"},
    "/api/v1/retrieval/settings": {"get", "put"},
    "/api/v1/retrieval/reindex-estimate": {"get"},
    "/api/v1/papers/{paper_id}/retrieval": {"get"},
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
        "input_budget",
        "input_tokens",
        "output_reserved",
        "summary_version",
        "recent_turns",
        "recalled_turns",
        "truncated",
    } <= set(usage)


def test_retrieval_dtos_have_exact_shapes():
    schemas = openapi()["components"]["schemas"]
    assert set(schemas["RetrievalSettings"]["properties"]) == {"embedding_profile", "reranker"}
    assert "PaperRetrievalUpdate" not in schemas
    assert {
        "effective_profile",
        "parser",
        "chunk_count",
        "section_count",
        "mode",
        "mode_note",
        "indexes",
    } <= set(schemas["PaperRetrieval"]["properties"])
    assert "source" not in schemas["PaperRetrieval"]["properties"]
    assert {"price_per_million"} <= set(schemas["EmbeddingProfileOut"]["properties"])
    assert {"profile", "papers", "tokens", "price_per_million", "estimated_cost_usd"} <= set(
        schemas["ReindexEstimate"]["properties"]
    )
    assert {"memory", "total_messages"} == set(schemas["ChatMemoryState"]["properties"])


def test_retrieval_settings_default_to_openai_profile_and_catalog_reranker():
    from app.integrations.reranker_catalog import DEFAULT_RERANKER
    from app.schemas.retrieval import RetrievalSettings

    # The user chose OpenAI reranking by default; the model lives in the catalog, not in code paths.
    assert RetrievalSettings().model_dump() == {
        "embedding_profile": "openai-3-large",
        "reranker": DEFAULT_RERANKER,
    }
    assert RetrievalSettings(reranker=None).reranker is None  # None means reranking is off


def test_reranker_catalog_is_extensible_like_embedding_profiles():
    from app.integrations.reranker_catalog import DEFAULT_RERANKER, RERANKERS, reranker_profile

    default = reranker_profile(DEFAULT_RERANKER)
    assert default.provider == "openai" and default.method == "openai-decisions"
    # User decision (2026-10-09): 40 candidates, about half of a paper's chunks (~2–3 s, ~$0.004).
    assert default.model_id == "gpt-6-luna" and default.candidates == 40
    local = next(p for p in RERANKERS.values() if p.provider == "ollama")
    assert local.method == "ollama-logprobs" and local.local_model_key and local.candidates == 12
    assert all(p.key == key for key, p in RERANKERS.items())


async def test_indexing_hook_is_a_safe_no_op_until_indexing_lands():
    from app.rag.hooks import after_chunks_persisted

    assert await after_chunks_persisted(None, document_id=None) is None


def test_profiles_page_reports_every_reranker_choice():
    schemas = openapi()["components"]["schemas"]
    page = schemas["EmbeddingProfilePage"]["properties"]
    assert "rerankers" in page and "reranker" not in page
    assert {
        "key",
        "provider",
        "model_id",
        "display_name",
        "status",
        "unavailable_reason",
        "local_model_key",
        "candidates",
    } <= set(schemas["RerankerOut"]["properties"])
    assert schemas["RerankerOut"]["properties"]["key"]["type"] == "string"


# What each search index model and reranker means for the user, from OpenAI's model pages and the
# catalog's measurements (read 2026-10-10, ARA-109). Frozen local entries keep their generic copy.
DESCRIPTIONS = {
    "openai-3-large": "OpenAI’s most capable search model, in English and other languages.",
    "openai-3-small": "A smaller model: cheaper to index, less capable than the large one.",
}
RERANKER_NOTES = {
    "openai-gpt-6-luna": "Adds about 2 to 3 seconds and $0.004 to each question.",
    "qwen3-rerank-0.6b": "Private, but adds about 10 seconds to each question.",
}


def test_given_the_retrieval_catalogs_when_read_then_hosted_models_say_what_they_mean():
    from app.integrations.embedding_catalog import PROFILES
    from app.integrations.reranker_catalog import RERANKERS

    assert {key: profile.description for key, profile in PROFILES.items()} == {
        **DESCRIPTIONS,
        "qwen3-embed-4b": None,
        "qwen3-embed-8b": None,
    }
    assert {key: profile.description for key, profile in RERANKERS.items()} == RERANKER_NOTES


def test_given_the_embedding_catalog_when_read_then_models_are_named_by_their_display_name():
    """Settings titles each search index model by its own name, with no label (ARA-109c)."""
    from app.integrations.embedding_catalog import PROFILES, EmbeddingProfile

    assert "label" not in EmbeddingProfile.__dataclass_fields__
    assert PROFILES["openai-3-large"].display_name == "OpenAI text-embedding-3-large"


def test_given_the_profiles_page_when_published_then_descriptions_and_reranker_price_are_fields():
    schemas = openapi()["components"]["schemas"]
    assert "description" in schemas["EmbeddingProfileOut"]["properties"]
    assert "label" not in schemas["EmbeddingProfileOut"]["properties"]
    assert {"description", "price_per_million"} <= set(schemas["RerankerOut"]["properties"])
