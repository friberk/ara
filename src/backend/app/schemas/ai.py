from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, field_validator

from app.schemas.jobs import JobError


class DTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Citation(DTO):
    chunk_id: UUID
    document_id: UUID
    page: int = Field(ge=1)
    excerpt: str


class GenerationInput(BaseModel):
    model: str = "gpt-5.6-luna"
    reasoning_effort: str = "low"
    request_id: UUID


class ChatInput(GenerationInput):
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must contain text")
        return value.strip()


class ChatCreate(BaseModel):
    title: str = Field(default="Paper discussion", min_length=1, max_length=200)


class ChatRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Installation(DTO):
    state: Literal[
        "missing",
        "queued",
        "downloading",
        "pausing",
        "paused",
        "verifying",
        "ready",
        "deleting",
        "failed",
    ]
    weights_present: bool
    quantization: str
    download_bytes: int
    completed_bytes: int = 0
    total_bytes: int | None = None
    job_id: UUID | None = None
    digest: str | None = None
    updated_at: datetime | None = None
    error: JobError | None = None


class ThinkingControls(BaseModel):
    values: list[StrictBool | str]
    default: StrictBool | str


class Model(DTO):
    thinking: ThinkingControls | None = None
    unavailable_reason: str | None = None
    unavailable_code: str | None = None
    installation: Installation | None = None
    key: str
    provider: str = "openai"
    model_id: str
    display_name: str
    status: Literal["configured", "available", "unavailable"]
    reasoning_efforts: list[str]
    supports_streaming: bool = True
    supports_structured_output: bool = True
    context_window: int = 1050000


class Defaults(BaseModel):
    default_model: str = "gpt-5.6-luna"
    reasoning_effort: str = "low"


class Summary(DTO):
    id: UUID
    paper_id: UUID
    document_id: UUID
    model: str
    reasoning_effort: str
    content: str
    citations: list[Citation]
    created_at: datetime


class SummaryPage(BaseModel):
    items: list[Summary]


class SummaryAccepted(BaseModel):
    job_id: UUID
    summary_id: UUID | None = None


class Chat(DTO):
    id: UUID
    paper_id: UUID
    document_id: UUID
    title: str
    title_source: Literal["default", "auto", "manual"]
    created_at: datetime


class ChatPage(BaseModel):
    items: list[Chat]


class ChatSummary(Chat):
    paper_title: str | None
    last_activity_at: datetime
    message_count: int
    last_question_preview: str | None


class ChatSummaryPage(BaseModel):
    items: list[ChatSummary]


class Message(DTO):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    state: Literal["completed", "processing", "interrupted", "failed"]
    model: str | None
    reasoning_effort: str | None
    citations: list[Citation]
    created_at: datetime


class MessagePage(BaseModel):
    items: list[Message]


class ModelPage(BaseModel):
    items: list[Model]
