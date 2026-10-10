"""Selectable embedding profiles. A profile key names one model at native dimensions."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.core.errors import AppError


@dataclass(frozen=True)
class EmbeddingProfile:
    key: str
    provider: Literal["openai", "ollama"]
    model_id: str
    display_name: str
    dimensions: int
    max_input_tokens: int
    batch_size: int
    query_instruction: str | None = None
    price_per_million: Decimal = Decimal("0")
    local_model_key: str | None = None
    # What choosing it means, in one plain sentence from its OpenAI model page, and a short name
    # for the choice that Settings shows before the model's own name (ARA-109).
    description: str | None = None
    label: str | None = None


# Qwen3 Embedding is instruction-aware on queries only; documents are embedded bare.
# A local batch is one admission to the shared retrieval slot, so it stays near 10 s of CPU
# work at the Phase 0 rates (4B 51 tok/s, 8B 29 tok/s) and a waiting search gets in next.
QWEN_QUERY = (
    "Instruct: Given a question about a scientific paper, retrieve passages of the paper "
    "that answer it\nQuery: "
)
PROFILES: dict[str, EmbeddingProfile] = {
    profile.key: profile
    for profile in (
        EmbeddingProfile(
            "openai-3-large",
            "openai",
            "text-embedding-3-large",
            "OpenAI text-embedding-3-large",
            3072,
            8191,
            64,
            price_per_million=Decimal("0.13"),
            # Tagline read 2026-10-10: "most capable embedding model for both english and
            # non-english tasks".
            description="OpenAI’s most capable search model, in English and other languages.",
            label="Higher quality",
        ),
        EmbeddingProfile(
            "openai-3-small",
            "openai",
            "text-embedding-3-small",
            "OpenAI text-embedding-3-small",
            1536,
            8191,
            64,
            price_per_million=Decimal("0.02"),
            # Tagline read 2026-10-10: "small embedding model"; the large one is "most capable".
            description="A smaller model: cheaper to index, less capable than the large one.",
            label="Lower cost",
        ),
        EmbeddingProfile(
            "qwen3-embed-4b",
            "ollama",
            "qwen3-embedding:4b-q4_K_M",
            "Qwen3 Embedding 4B",
            2560,
            32768,
            2,
            QWEN_QUERY,
            local_model_key="qwen3-embedding-4b",
        ),
        EmbeddingProfile(
            "qwen3-embed-8b",
            "ollama",
            "qwen3-embedding:8b-q4_K_M",
            "Qwen3 Embedding 8B",
            4096,
            32768,
            1,
            QWEN_QUERY,
            local_model_key="qwen3-embedding-8b",
        ),
    )
}
DEFAULT_PROFILE = "openai-3-large"


def embedding_profile(key: str) -> EmbeddingProfile:
    profile = PROFILES.get(key)
    if profile is None:
        raise AppError(
            422, "INVALID_EMBEDDING_PROFILE", "Choose one of the supported embedding models."
        )
    return profile
