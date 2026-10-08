from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Provider = Literal["openalex", "semantic_scholar"]


class SearchResult(BaseModel):
    provider: Provider
    external_id: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    doi: str | None = None
    external_url: str | None = None
    pdf_url: str | None = None


class SearchPage(BaseModel):
    provider: Provider
    items: list[SearchResult]
    next_cursor: str | None = None
    total: int | None = None


class SavePaper(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider
    external_id: str = Field(min_length=1, max_length=200)


class PaperDetail(BaseModel):
    id: UUID
    title: str | None
    authors: list[str]
    year: int | None
    abstract: str | None
    doi: str | None
    sources: list[SearchResult]
    document_status: Literal["metadata_only", "processing", "ready", "failed"]
    active_document_id: UUID | None
    metadata_provenance: dict


class PaperPage(BaseModel):
    items: list[PaperDetail]


class PaperPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=1000)
    authors: list[str] | None = Field(default=None, max_length=50)
    year: int | None = Field(default=None, ge=1500, le=2100)
    abstract: str | None = Field(default=None, max_length=20000)
    doi: str | None = Field(default=None, max_length=300)


class UploadAccepted(BaseModel):
    paper_id: UUID
    document_id: UUID
    job_id: UUID


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    page: int
    excerpt: str
