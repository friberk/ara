from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Provider = Literal["openalex", "semantic_scholar"]


class FullTextLocation(BaseModel):
    pdf_url: str | None = None
    landing_page_url: str | None = None
    is_oa: bool | None = None
    license: str | None = None
    version: str | None = None
    host_type: Literal["publisher", "repository", "unknown"] = "unknown"
    oa_status: str | None = None


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
    is_open_access: bool | None = None
    locations: list[FullTextLocation] = Field(default_factory=list)
    # Journal or conference name; older stored snapshots have none (ARA-086).
    venue: str | None = None


class SearchHit(SearchResult):
    """A search result plus library state; stored provider snapshots stay SearchResult."""

    saved_paper_id: UUID | None = None


class SearchPage(BaseModel):
    provider: Provider
    items: list[SearchHit]
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
    # From the linked provider record; papers have no venue column (ARA-086).
    venue: str | None = None
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
    # True when a new request matched a PDF the library already holds (ARA-086).
    duplicate: bool = False


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    page: int
    # Structured-chunk provenance, matching app.schemas.ai.Citation (ARA-071).
    page_end: int | None = None
    section: str | None = None
    kind: Literal["front_matter", "text", "table", "references"] | None = None
    bboxes: list[list[float]] = Field(default_factory=list)
    excerpt: str


class SearchHistoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class SearchHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    provider: Provider
    query: str
    created_at: datetime
    last_searched_at: datetime


class SearchHistoryPage(BaseModel):
    items: list[SearchHistoryItem]
