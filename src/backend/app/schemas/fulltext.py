"""Full-text retrieval values (OpenAlex content, ARA-087); PDF bytes never reach the API."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.jobs import JobStatus

FullTextOutcome = Literal[
    "downloaded",
    "not_stored",
    "api_key_required",
    "rate_limited",
    "unavailable",
    "invalid_pdf",
    "unsafe_url",
    "already_attached",
    "superseded",
]


@dataclass
class DownloadResult:
    outcome: FullTextOutcome
    data: bytes | None = None
    response_status: int | None = None
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


class FullTextStatus(BaseModel):
    paper_id: UUID
    # Without an OpenAlex API key nothing is downloaded; the workspace asks for an upload.
    api_key_configured: bool
    retrieval_job: JobStatus | None = None
    document_id: UUID | None = None
    ingest_job_id: UUID | None = None
    acquisition: dict | None = None
