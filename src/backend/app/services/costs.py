"""Spend in USD, priced from the model catalogs at the tokens a call recorded (ARA-085)."""

from decimal import Decimal

from app.core.errors import AppError
from app.integrations.embedding_catalog import embedding_profile
from app.integrations.llm import PRICES
from app.integrations.model_catalog import local_spec
from app.integrations.reranker_catalog import reranker_profile

MILLION = Decimal(1_000_000)


def token_count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def call_cost(model: str, usage: dict) -> Decimal | None:
    """A chat call's cost. Local models are free; an unknown model or missing usage has none."""
    if local_spec(model):
        return Decimal(0)
    prices = PRICES.get(model)
    tokens = (token_count(usage.get("input_tokens")), token_count(usage.get("output_tokens")))
    if prices is None or None in tokens:
        return None
    return (prices[0] * tokens[0] + prices[1] * tokens[1]) / MILLION


def embedding_cost(profile: str, tokens: int) -> Decimal | None:
    try:
        return embedding_profile(profile).price_per_million * tokens / MILLION
    except AppError:
        return None


def rerank_cost(profile: str, tokens: int) -> Decimal | None:
    try:
        return reranker_profile(profile).price_per_million_input * tokens / MILLION
    except AppError:
        return None
