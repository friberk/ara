"""Spend in USD, priced from the model catalogs at the tokens a call recorded (ARA-085)."""

from dataclasses import dataclass
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


@dataclass
class Spend:
    """A chat's recorded spend by kind, and whether any hosted call was among them."""

    answers: Decimal = Decimal(0)
    planning: Decimal = Decimal(0)
    compaction: Decimal = Decimal(0)
    embeddings: Decimal = Decimal(0)
    reranking: Decimal = Decimal(0)
    unrecorded_turns: int = 0
    hosted: bool = False
    local: bool = False

    @property
    def total(self) -> Decimal:
        return self.answers + self.planning + self.compaction + self.embeddings + self.reranking

    def chat_call(self, kind: str, model: str, usage) -> None:
        if not isinstance(usage, dict):
            return
        cost = call_cost(model, usage)
        if cost is None:
            return
        setattr(self, kind, getattr(self, kind) + cost)
        self.local, self.hosted = (
            self.local or bool(local_spec(model)),
            self.hosted or not (local_spec(model)),
        )

    def retrieval_call(self, kind: str, price, profile, tokens) -> None:
        tokens = token_count(tokens)
        cost = None if tokens is None or not isinstance(profile, str) else price(profile, tokens)
        if cost is None:
            return
        setattr(self, kind, getattr(self, kind) + cost)
        self.hosted = self.hosted or cost > 0


def message_spend(spend: Spend, state: str, model, usage, billed) -> None:
    """Add one assistant message: its answer, and the calls made to find its evidence.

    Calls made for an answer that later failed were still billed, so `billed` counts in any
    state; a completed answer with no recorded usage is counted, never estimated.
    """
    if usage:
        spend.chat_call("answers", model or "", usage)
    elif state == "completed":
        spend.unrecorded_turns += 1
    if not isinstance(billed, dict):
        return
    planner = billed.get("planner")
    if isinstance(planner, dict):
        spend.chat_call("planning", str(planner.get("model", "")), planner)
    embedding, rerank = billed.get("embedding"), billed.get("rerank")
    if isinstance(embedding, dict):
        spend.retrieval_call(
            "embeddings", embedding_cost, embedding.get("profile"), embedding.get("tokens")
        )
    if isinstance(rerank, dict):
        spend.retrieval_call("reranking", rerank_cost, rerank.get("profile"), rerank.get("tokens"))
