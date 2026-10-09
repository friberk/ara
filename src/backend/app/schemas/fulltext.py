"""Shared full-text discovery/download values; PDF bytes are never serialized in the API."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.jobs import JobStatus
from app.schemas.research import FullTextLocation, Provider

FullTextOutcome = Literal[
    "downloaded",
    "access_required",
    "blocked",
    "not_found",
    "rate_limited",
    "unavailable",
    "invalid_pdf",
    "unsafe_url",
    "unsupported_source",
    "no_pdf_link",
    "already_attached",
    "superseded",
]


class FullTextCandidate(BaseModel):
    provider: Provider
    external_id: str
    source_label: str
    url: str
    location: FullTextLocation


@dataclass
class DownloadResult:
    outcome: FullTextOutcome
    data: bytes | None = None
    response_status: int | None = None
    final_url: str | None = None
    reason: str = ""
    retry_after: int | None = None


class FullTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class FullTextAccepted(BaseModel):
    paper_id: UUID
    job_id: UUID


class AutomaticFullText(BaseModel):
    paper_id: UUID
    # The paper's automatic retrieval job, or null when the paper does not qualify.
    job_id: UUID | None = None


class FullTextAttemptView(BaseModel):
    provider: Provider
    source_label: str
    version: str | None = None
    is_oa: bool | None = None
    license: str | None = None
    response_status: int | None = None
    outcome: FullTextOutcome
    reason: str
    checked_at: datetime


class FullTextStatus(BaseModel):
    paper_id: UUID
    availability: Literal["open_copy_reported", "publisher_link_only", "unknown"]
    locations: list[FullTextLocation] = Field(default_factory=list)
    retrieval_job: JobStatus | None = None
    document_id: UUID | None = None
    ingest_job_id: UUID | None = None
    last_checked_at: datetime | None = None
    attempts: list[FullTextAttemptView] = Field(default_factory=list)
    acquisition: dict | None = None
