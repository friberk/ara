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


class PaperLink(BaseModel):
    paper_id: UUID
    title: str | None


class UploadMatch(PaperLink):
    """A new upload that is this library paper; it waits for Replace/Attach or Cancel (ARA-086)."""

    has_pdf: bool
    matched_by: Literal["doi", "arxiv", "title"]
    found_by: Literal["ingest", "lookup"]


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
    # The active PDF's file name, so an untitled paper can be named while it is read (ARA-086).
    file_name: str | None = None
    upload_match: UploadMatch | None = None
    # The active PDF's DOI belongs to this other library paper.
    pdf_doi_owner: PaperLink | None = None


class PaperPage(BaseModel):
    items: list[PaperDetail]


class PaperPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=1000)
    authors: list[str] | None = Field(default=None, max_length=50)
    year: int | None = Field(default=None, ge=1500, le=2100)
    abstract: str | None = Field(default=None, max_length=20000)
    doi: str | None = Field(default=None, max_length=300)
    # Kept in metadata_provenance.venue as {source: manual, value}; papers have no venue column.
    venue: str | None = Field(default=None, max_length=300)


class PaperIds(BaseModel):
    """Papers to preview or delete together (ARA-095)."""

    model_config = ConfigDict(extra="forbid")
    paper_ids: list[UUID] = Field(min_length=1, max_length=200)


class ChatLink(BaseModel):
    id: UUID
    title: str


class DeletionPreview(BaseModel):
    """What deleting these papers removes; reading it changes nothing (ARA-095)."""

    papers: list[PaperLink]
    # Requested IDs that name no paper, in request order.
    missing: list[UUID]
    # Stored PDFs, every version.
    pdfs: int
    summaries: int
    # Chats about only these papers; they are deleted.
    deleted_chats: list[ChatLink]
    # Chats that also cover other papers; they keep those and their saved citations.
    updated_chats: list[ChatLink]
    # Queued or running work for these papers; it stops.
    active_jobs: int
    # A chat is writing an answer now; deletion waits for it (409 CHAT_BUSY).
    answering: bool


class DeletedPapers(BaseModel):
    deleted: list[UUID]
    missing: list[UUID]


class DocumentDetail(BaseModel):
    """One PDF's file facts, for the reader's PDF menu (ARA-097)."""

    id: UUID
    paper_id: UUID
    file_name: str
    page_count: int | None
    byte_size: int
    status: Literal["uploading", "processing", "ready", "failed"]
    # How a retrieved PDF was acquired (ARA-087); null for an upload.
    acquisition: dict | None
    created_at: datetime


class PdfRemovalPreview(BaseModel):
    """What removing the paper's PDF changes; reading it changes nothing (ARA-097)."""

    # The paper's PDFs: the current one and earlier versions. All are removed.
    pdfs: int
    # Summaries of those PDFs; they are deleted.
    summaries: int
    # Chats that use one of those PDFs; they stay readable and take no new questions.
    chats: list[ChatLink]
    # Queued or running work on those PDFs; it stops.
    active_jobs: int
    # One of those chats is writing an answer now; removal waits for it (409 CHAT_BUSY).
    answering: bool


class MatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # attach also replaces the library paper's PDF; discard removes the upload.
    decision: Literal["attach", "discard"]


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
