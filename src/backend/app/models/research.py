from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    abstract: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(300))
    normalized_doi: Mapped[str | None] = mapped_column(String(300), unique=True)
    active_document_id: Mapped[UUID | None]
    retrieval_profile: Mapped[str | None] = mapped_column(String(40))
    metadata_provenance: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperAuthor(Base):
    __tablename__ = "paper_authors"
    __table_args__ = (UniqueConstraint("paper_id", "ordinal", name="uq_author_ordinal"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    ordinal: Mapped[int]
    name: Mapped[str] = mapped_column(String(300))


class PaperSource(Base):
    __tablename__ = "paper_sources"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_source_identity"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(200))
    metadata_snapshot: Mapped[dict] = mapped_column(JSONB)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploading','processing','ready','failed')", name="document_status"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="uploading")
    object_key: Mapped[str] = mapped_column(String(100), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    original_filename: Mapped[str] = mapped_column(String(160))
    byte_size: Mapped[int]
    request_id: Mapped[UUID] = mapped_column(unique=True)
    ingest_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("background_jobs.id"))
    page_count: Mapped[int | None]
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    extractor_version: Mapped[str | None] = mapped_column(String(80))
    parser: Mapped[str | None] = mapped_column(String(40))
    chunk_set: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page", name="uq_document_page"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    printed_label: Mapped[str | None] = mapped_column(String(80))


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_set", "ordinal", name="uq_document_chunk_ordinal"),
        CheckConstraint("kind IN ('front_matter','text','table','references')", name="chunk_kind"),
        Index("ix_chunk_search", "search_vector", postgresql_using="gin"),
        Index("ix_chunk_document", "document_id", "chunk_set", "ordinal"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_set: Mapped[str] = mapped_column(String(80))
    ordinal: Mapped[int]
    section_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_sections.id", ondelete="SET NULL")
    )
    section_path: Mapped[list] = mapped_column(JSONB, default=list)
    heading: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="text")
    page: Mapped[int]
    page_end: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    context_text: Mapped[str] = mapped_column(Text)
    bboxes: Mapped[list] = mapped_column(JSONB, default=list)
    token_count: Mapped[int]
    # Headings weigh more than body text in keyword search.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', heading), 'A') || "
            "setweight(to_tsvector('english', text), 'B')",
            persisted=True,
        ),
    )


class PaperSummary(Base):
    __tablename__ = "paper_summaries"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"))
    model: Mapped[str] = mapped_column(String(80))
    reasoning_effort: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    configuration: Mapped[dict] = mapped_column(JSONB, default=dict)
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("title_source IN ('default','auto','manual')", name="chat_title_source"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"))
    title: Mapped[str] = mapped_column(String(200), default="Paper discussion")
    title_source: Mapped[str] = mapped_column(
        String(20), default="default", server_default="default"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="message_role"),
        CheckConstraint(
            "state IN ('processing','completed','interrupted','failed')", name="message_state"
        ),
        CheckConstraint("grounding IN ('supported','insufficient')", name="message_grounding"),
        Index(
            "uq_chat_request",
            "session_id",
            "request_id",
            unique=True,
            postgresql_where=text("role = 'user'"),
        ),
        Index(
            "uq_chat_processing",
            "session_id",
            unique=True,
            postgresql_where=text("role = 'assistant' AND state = 'processing'"),
        ),
        Index("ix_chat_message_activity", "session_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default="completed")
    model: Mapped[str | None] = mapped_column(String(80))
    reasoning_effort: Mapped[str | None] = mapped_column(String(20))
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    configuration: Mapped[dict] = mapped_column(JSONB, default=dict)
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    request_id: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieval: Mapped[dict] = mapped_column(JSONB, default=dict)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    grounding: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelConfiguration(Base):
    __tablename__ = "model_configurations"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)


class GenerationReservation(Base):
    __tablename__ = "generation_reservations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    model: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentUploadRequest(Base):
    __tablename__ = "document_upload_requests"
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchHistory(Base):
    __tablename__ = "search_history"
    __table_args__ = (
        UniqueConstraint("provider", "normalized_query", name="uq_search_history_query"),
        Index("ix_search_history_recent", "last_searched_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(40))
    query: Mapped[str] = mapped_column(Text)
    # Casefolding can expand a character into three, so 300 input characters need 900.
    normalized_query: Mapped[str] = mapped_column(String(900))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
