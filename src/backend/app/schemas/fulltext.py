"""Shared full-text discovery/download values; PDF bytes are never serialized in the API."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

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
