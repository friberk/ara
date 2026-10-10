"""Reranker profiles, extensible like embedding profiles (ARA-074).

A profile names a provider, a model and the scoring method. Adding a model (for example a newer
OpenAI model supported by the Decisions API) is a new entry here, not a code change elsewhere.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.core.errors import AppError

RELEVANCE_INSTRUCTIONS = (
    "Does this passage from a scientific paper contain information that helps answer the query? "
    "Judge semantic relevance, not keyword overlap."
)


@dataclass(frozen=True)
class RerankerProfile:
    key: str
    provider: Literal["openai", "ollama"]
    method: Literal["openai-decisions", "ollama-logprobs"]
    model_id: str
    display_name: str
    candidates: int  # fused candidates scored per question
    concurrency: int  # parallel scoring calls
    price_per_million_input: Decimal = Decimal("0")
    local_model_key: str | None = None
    # What choosing it adds to each question, from the measurements below (ARA-109).
    description: str | None = None


RERANKERS: dict[str, RerankerProfile] = {
    profile.key: profile
    for profile in (
        # Measured 2026-10-09: 20 candidates in 1.2 s at concurrency 8, 12/12 probe pairs, ~$0.002.
        # The user chose 40 candidates (about half of a paper's chunks; ~2–3 s, ~$0.004).
        RerankerProfile(
            key="openai-gpt-6-luna",
            provider="openai",
            method="openai-decisions",
            model_id="gpt-6-luna",
            display_name="OpenAI GPT-6 Luna",
            candidates=40,
            concurrency=8,
            price_per_million_input=Decimal("0.10"),
            description="Adds about 2 to 3 seconds and $0.004 to each question.",
        ),
        # Measured 2026-10-09: 12 candidates in about 9 s on 4 CPUs, 12/12 probe pairs.
        RerankerProfile(
            key="qwen3-rerank-0.6b",
            provider="ollama",
            method="ollama-logprobs",
            model_id="fanyx/Qwen3-Reranker-0.6B-Q8_0",
            display_name="Qwen3 Reranker 0.6B (local)",
            candidates=12,
            concurrency=1,
            local_model_key="qwen3-reranker-0.6b",
            description="Private, but adds about 10 seconds to each question.",
        ),
    )
}
DEFAULT_RERANKER = "openai-gpt-6-luna"


def reranker_profile(key: str) -> RerankerProfile:
    try:
        return RERANKERS[key]
    except KeyError:
        raise AppError(422, "INVALID_RERANKER", "That reranker is not supported.") from None
