"""Chat spend is priced from the catalogs at the tokens each call recorded (ARA-085)."""

from decimal import Decimal

from app.integrations.embedding_catalog import PROFILES
from app.integrations.llm import PRICES
from app.integrations.model_catalog import LOCAL_MODELS
from app.integrations.reranker_catalog import RERANKERS


def test_given_a_hosted_call_when_priced_then_tokens_use_the_catalog_rates():
    from app.services.costs import call_cost

    cheap_in, cheap_out = PRICES["gpt-5.6-luna"]
    cost = call_cost("gpt-5.6-luna", {"input_tokens": 20_000, "output_tokens": 500})
    assert cost == (cheap_in * 20_000 + cheap_out * 500) / Decimal(1_000_000)
    dear_in, _ = PRICES["gpt-5.6-sol"]
    assert call_cost("gpt-5.6-sol", {"input_tokens": 1_000_000, "output_tokens": 0}) == dear_in


def test_given_a_local_call_when_priced_then_it_is_free():
    from app.services.costs import call_cost

    key = next(iter(LOCAL_MODELS))
    assert call_cost(key, {"input_tokens": 9_999, "output_tokens": 999}) == Decimal(0)


def test_given_an_unknown_model_or_missing_usage_when_priced_then_nothing_is_invented():
    from app.services.costs import call_cost

    assert call_cost("retired-model", {"input_tokens": 5, "output_tokens": 5}) is None
    assert call_cost("gpt-5.6-luna", {}) is None
    assert call_cost("gpt-5.6-luna", {"input_tokens": "many"}) is None


def test_given_embedding_and_rerank_profiles_when_priced_then_each_uses_its_own_rate():
    from app.services.costs import embedding_cost, rerank_cost

    hosted = PROFILES["openai-3-large"]
    assert embedding_cost(hosted.key, 1_000_000) == hosted.price_per_million
    assert embedding_cost("qwen3-embed-4b", 1_000_000) == Decimal(0)
    reranker = RERANKERS["openai-gpt-6-luna"]
    assert rerank_cost(reranker.key, 1_000_000) == reranker.price_per_million_input
    assert rerank_cost("qwen3-rerank-0.6b", 1_000_000) == Decimal(0)
    assert embedding_cost("retired", 10) is None and rerank_cost("retired", 10) is None
