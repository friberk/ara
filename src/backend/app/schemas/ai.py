from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.jobs import JobError


class DTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Citation(DTO):
    chunk_id: UUID
    document_id: UUID
    # The paper the cited PDF belongs to, filled when chat history is read (ARA-088).
    paper_id: UUID | None = None
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
    # A comparative question's per-paper sub-questions, each searched in its paper (ARA-088).
    sub_questions: list[str] = Field(default_factory=list)
    passages_found: int = 0
    passages_used: int = 0
    # Candidates dropped for scoring far below the best one, and the tokens of the evidence sent
    # (ARA-094).
    pruned: int = 0
    evidence_tokens: int = 0
    # Section summaries among the passages used (ARA-079).
    summaries_used: int = 0
    # The planner's classification; a broad question grows chunks to their section (ARA-094).
    question_type: Literal["lookup", "broad", "comparative"] | None = None
    # The first answer reported insufficient evidence and one wider retry replaced it (ARA-094).
    retried: bool = False
    # A small window read each paper in its own call, then combined their notes (ARA-094).
    map_reduce: bool = False
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


class PaperMention(BaseModel):
    """A library paper a question mentions with a composer pill (ARA-096). `label` is the pill's
    text, which the question holds at [start, end): Unicode code points of the trimmed content,
    as Python indexes strings."""

    paper_id: UUID
    label: str = Field(min_length=1, max_length=500)
    start: int = Field(ge=0)
    end: int = Field(ge=1)


class ChatInput(GenerationInput):
    content: str = Field(min_length=1, max_length=8000)
    # Mentioned papers not yet in the chat join it with this question (ARA-096).
    mentions: list[PaperMention] = Field(default_factory=list)

    @field_validator("content")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must contain text")
        return value.strip()

    @model_validator(mode="after")
    def mentions_in_text(self):
        """Each pill's label sits at its span, in order and without overlaps."""
        previous = 0
        for mention in self.mentions:
            if not mention.label.strip():
                raise ValueError("A mention needs a label")
            if mention.start < previous or self.content[mention.start : mention.end] != (
                mention.label
            ):
                raise ValueError("Mentions must match the question text, in order")
            previous = mention.end
        return self


class ChatCreate(BaseModel):
    """The papers a new chat covers, in order, any number of them (ARA-088); the first one's
    page is the chat's URL."""

    paper_ids: list[UUID] = Field(min_length=1)
    title: str = Field(default="Paper discussion", min_length=1, max_length=200)

    @field_validator("paper_ids")
    @classmethod
    def distinct(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Each paper can be included once")
        return value


class ChatPaperAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paper_id: UUID


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
    context_window: int


class Features(BaseModel):
    """Server features the browser adapts to (ARA-090)."""

    open_models: bool


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


class IncludedPaper(BaseModel):
    """A library paper in a chat, with the PDF pinned for it when it joined (ARA-088)."""

    paper_id: UUID
    document_id: UUID
    title: str | None
    first_author: str | None
    year: int | None
    added_at: datetime
    # The pinned PDF was removed from its paper (ARA-097): earlier answers still read, but the
    # chat takes no new questions.
    pdf_removed: bool = False


class Chat(BaseModel):
    id: UUID
    # The first included paper; the chat's URL is /papers/{paper_id}/chats/{id}.
    paper_id: UUID
    papers: list[IncludedPaper]
    title: str
    title_source: Literal["default", "auto", "manual"]
    created_at: datetime


class ChatPage(BaseModel):
    items: list[Chat]


class ChatSummary(Chat):
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
    # A question's pills, stored in its configuration (ARA-096); older questions have none.
    mentions: list[PaperMention] = Field(
        default_factory=list, validation_alias=AliasPath("configuration", "mentions")
    )

    @field_validator("retrieval", "context", mode="before")
    @classmethod
    def empty_json_is_absent(cls, value):
        # Persisted JSONB defaults to {} for messages written before retrieval traces existed.
        return value or None


class MessagePage(BaseModel):
    items: list[Message]


class ModelPage(BaseModel):
    items: list[Model]
