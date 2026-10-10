"""Retrieval controls, paper indexes and conversation memory contracts (ARA-070)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.jobs import JobError


class EmbeddingProfileOut(BaseModel):
    key: str
    provider: Literal["openai", "ollama"]
    model_id: str
    display_name: str
    dimensions: int
    status: Literal["available", "unavailable"]
    unavailable_reason: str | None = None
    local_model_key: str | None = None
    # US dollars per million input tokens; 0 for local models.
    price_per_million: float = 0
    # What choosing it means, for hosted models (ARA-109).
    description: str | None = None


class RerankerOut(BaseModel):
    """A reranker profile from the catalog (ARA-074)."""

    key: str
    provider: Literal["openai", "ollama"]
    model_id: str
    display_name: str
    status: Literal["available", "unavailable"]
    unavailable_reason: str | None = None
    local_model_key: str | None = None
    candidates: int
    # US dollars per million input tokens, and what choosing it adds to each question (ARA-109).
    price_per_million: float = 0
    description: str | None = None


class EmbeddingProfilePage(BaseModel):
    items: list[EmbeddingProfileOut]
    default_profile: str
    rerankers: list[RerankerOut] = Field(default_factory=list)


class RetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embedding_profile: str = "openai-3-large"
    # A reranker profile key from app.integrations.reranker_catalog; None turns reranking off.
    # User decision (ARA-074): OpenAI reranking by default (DEFAULT_RERANKER).
    reranker: str | None = "openai-gpt-6-luna"

    @classmethod
    def from_stored(cls, value: dict | None) -> "RetrievalSettings":
        """Read a stored row, ignoring keys from earlier contract versions."""
        value = value or {}
        return cls.model_validate({k: v for k, v in value.items() if k in cls.model_fields})


class RetrievalIndexOut(BaseModel):
    profile: str
    state: Literal["queued", "embedding", "ready", "failed", "unavailable"]
    embedded: int
    total: int
    updated_at: datetime | None = None
    error: JobError | None = None


class PaperRetrieval(BaseModel):
    paper_id: UUID
    document_id: UUID | None
    effective_profile: str
    parser: str | None
    chunk_count: int
    section_count: int
    mode: Literal["hybrid", "keyword", "unavailable"]
    mode_note: str | None = None
    indexes: list[RetrievalIndexOut]


class ReindexEstimate(BaseModel):
    """What switching the library embedding model would re-embed (ARA-091)."""

    profile: str
    papers: int
    tokens: int
    price_per_million: float
    estimated_cost_usd: float


class RebuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class ChatMemoryOut(BaseModel):
    version: int
    summary: str
    summarized_messages: int
    model: str
    created_at: datetime


class ChatMemoryState(BaseModel):
    memory: ChatMemoryOut | None
    total_messages: int
