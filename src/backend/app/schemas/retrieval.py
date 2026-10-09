"""Retrieval controls, paper indexes and conversation memory contracts (ARA-070)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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


class EmbeddingProfilePage(BaseModel):
    items: list[EmbeddingProfileOut]
    default_profile: str


class RetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embedding_profile: str = "openai-3-large"
    # ARA-074 deferred: CPU reranking measured ~54 s per question (Phase 0 S1).
    reranker_enabled: bool = False


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
    source: Literal["default", "paper"]
    parser: str | None
    chunk_count: int
    section_count: int
    mode: Literal["hybrid", "keyword", "unavailable"]
    mode_note: str | None = None
    indexes: list[RetrievalIndexOut]


class PaperRetrievalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str | None
    request_id: UUID


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
