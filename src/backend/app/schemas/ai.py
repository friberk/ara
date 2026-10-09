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
    page_end: int | None = Field(default=None, ge=1)
    section: str | None = None
    kind: Literal["front_matter", "text", "table", "references"] | None = None
    bboxes: list[list[float]] = Field(default_factory=list)
    excerpt: str


class RetrievalSummary(BaseModel):
    """How an answer's evidence was found; persisted on the assistant message."""

    mode: Literal["hybrid", "keyword"]
    profile: str | None = None
    reranked: bool = False
    standalone_query: str | None = None
    search_queries: list[str] = Field(default_factory=list)
    passages_found: int = 0
    passages_used: int = 0
    limited_by_context: bool = False
    note: str | None = None


class ContextUsage(BaseModel):
    """Token accounting for one answer request."""

    window: int
    # The input cap that applied: the window less output and thinking, or a working cap.
    input_budget: int | None = None
    input_tokens: int
    output_reserved: int
    summary_version: int | None = None
    recent_turns: int = 0
    recalled_turns: int = 0
    truncated: bool = False


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
    operation: Literal["download", "verify", "delete"] | None = None
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
    reasoning_aliases: dict[str, str] = Field(default_factory=dict)
    thinking: ThinkingControls | None = None
    unavailable_reason: str | None = None
    unavailable_code: str | None = None
    installation: Installation | None = None
    kind: Literal["chat", "embedding", "reranker"] = "chat"
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
    # A hosted chat-model key. Hosted chats summarize earlier messages and plan follow-up
    # searches with it at its quietest effort; local chats use their own model (ARA-077).
    memory_model: str = "gpt-5.6-luna"


class Summary(DTO):
    id: UUID
    paper_id: UUID
    document_id: UUID
    model: str
    reasoning_effort: str
    content: str
    citations: list[Citation]
    created_at: datetime


class SummaryBlock(BaseModel):
    code: str
    message: str
    model: str
    reasoning_effort: str


class SummaryPage(BaseModel):
    items: list[Summary]
    # Why the saved default model cannot summarize the active PDF now, while it has no summary
    # or running summary job; an automatic summary of a newly ready PDF skips for this reason.
    blocked: SummaryBlock | None = None


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
    retrieval: RetrievalSummary | None = None
    context: ContextUsage | None = None
    grounding: Literal["supported", "insufficient"] | None = None

    @field_validator("retrieval", "context", mode="before")
    @classmethod
    def empty_json_is_absent(cls, value):
        # Persisted JSONB defaults to {} for messages written before retrieval traces existed.
        return value or None


class MessagePage(BaseModel):
    items: list[Message]


class ModelPage(BaseModel):
    items: list[Model]
